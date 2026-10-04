"""Documents blueprint routes"""
# pylint: disable=duplicate-code

import datetime as dt
import hashlib
from http import HTTPStatus
from pathlib import Path

from flask import current_app, g, jsonify, request, send_file
from sqlalchemy import text
from werkzeug.utils import secure_filename

from ..auth.tokens import require_auth
from ..db import get_engine
from . import bp


def _sha256_file(path: Path) -> str:
    """Calculate SHA256 checksum for file"""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_resolve_under_storage(path: str, storage_root: Path) -> Path:
    """Check sanity of file path"""

    storage_root = storage_root.resolve()
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = storage_root / file_path
    file_path = file_path.resolve()
    if hasattr(file_path, "is_relative_to"):
        if not file_path.is_relative_to(storage_root):
            raise RuntimeError(f"path {file_path} escapes storage root {storage_root}")
    else:
        try:
            file_path.relative_to(storage_root)
        except ValueError as e:
            raise RuntimeError(f"path {file_path} escapes storage root {storage_root}") from e
    return file_path


@bp.post("/upload-document")
@require_auth
def upload_document():
    """Upload new document for user"""

    if "file" not in request.files:
        return jsonify(
            {"error": "file is required (multipart/form-data)"}
        ), HTTPStatus.BAD_REQUEST
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "empty filename"}), HTTPStatus.BAD_REQUEST

    filename = secure_filename(file.filename)
    if not filename:
        return jsonify({"error": "invalid filename"}), HTTPStatus.BAD_REQUEST

    storage_root = Path(current_app.config["STORAGE_DIR"]).resolve()
    user_directory = _safe_resolve_under_storage(
        f"files/{int(g.user['id'])}",
        storage_root,
    )
    user_directory.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    final_name = request.form.get("name") or filename
    stored_name = f"{timestamp}__{filename}"
    stored_path = _safe_resolve_under_storage(
        str(user_directory / stored_name),
        storage_root,
    )
    file.save(stored_path)

    sha256_hex = _sha256_file(stored_path)
    size = stored_path.stat().st_size

    try:
        with get_engine().begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO Documents (name, path, ownerid, sha256, size)
                    VALUES (:name, :path, :ownerid, UNHEX(:sha256hex), :size)
                    """
                ),
                {
                    "name": final_name,
                    "path": str(stored_path),
                    "ownerid": int(g.user["id"]),
                    "sha256hex": sha256_hex,
                    "size": int(size),
                },
            )
            document_id = int(
                connection.execute(text("SELECT LAST_INSERT_ID()")).scalar()
            )
            row = connection.execute(
                text(
                    """
                    SELECT id, name, creation, HEX(sha256) AS sha256_hex, size
                    FROM Documents
                    WHERE id = :id
                    """
                ),
                {"id": document_id},
            ).one()
    except Exception:  # pylint: disable=broad-exception-caught
        # TODO: Log the error and remove the stored
        # file when the database transaction fails
        current_app.logger.exception("DB error while uploading document")
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    return jsonify(
        {
            "id": int(row.id),
            "name": row.name,
            "creation": (
                row.creation.isoformat()
                if hasattr(row.creation, "isoformat")
                else str(row.creation)
            ),
            "sha256": row.sha256_hex,
            "size": int(row.size),
        }
    ), HTTPStatus.CREATED


@bp.get("/list-documents")
@require_auth
def list_documents():
    """List all documents owned by user"""

    try:
        with get_engine().connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT id, name, creation, HEX(sha256) AS sha256_hex, size
                    FROM Documents
                    WHERE ownerid = :uid
                    ORDER BY creation DESC
                    """
                ),
                {"uid": int(g.user["id"])},
            ).all()
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception("DB error while listing documents")
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    documents = [
        {
            "id": int(row.id),
            "name": row.name,
            "creation": (
                row.creation.isoformat()
                if hasattr(row.creation, "isoformat")
                else str(row.creation)
            ),
            "sha256": row.sha256_hex,
            "size": int(row.size),
        }
        for row in rows
    ]
    return jsonify({"documents": documents}), HTTPStatus.OK


@bp.get("/list-versions")
@bp.get("/list-versions/<int:document_id>")
@require_auth
def list_versions(document_id: int | None = None):
    """List all versions of document owned by user"""

    if document_id is None:
        document_id = request.args.get("id") or request.args.get("documentid")
        try:
            document_id = int(document_id)
        except (TypeError, ValueError):
            return jsonify({"error": "document id required"}), HTTPStatus.BAD_REQUEST

    try:
        with get_engine().connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT v.id, v.documentid, v.link, v.intended_for,
                           v.secret, v.method
                    FROM Documents d
                    JOIN Versions v ON d.id = v.documentid
                    WHERE d.ownerid = :gid AND d.id = :did
                    """
                ),
                {"gid": int(g.user["id"]), "did": document_id},
            ).all()
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while listing versions for document id=%s",
            document_id,
        )
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    versions = [
        {
            "id": int(row.id),
            "documentid": int(row.documentid),
            "link": row.link,
            "intended_for": row.intended_for,
            "secret": row.secret,
            "method": row.method,
        }
        for row in rows
    ]
    return jsonify({"versions": versions}), HTTPStatus.OK


@bp.get("/list-all-versions")
@require_auth
def list_all_versions():
    """List all versions of documents owned by user"""

    try:
        with get_engine().connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT v.id, v.documentid, v.link, v.intended_for, v.method
                    FROM Documents d
                    JOIN Versions v ON d.id = v.documentid
                    WHERE d.ownerid = :gid
                    """
                ),
                {"gid": int(g.user["id"])},
            ).all()
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception("DB error while listing all versions")
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    versions = [
        {
            "id": int(row.id),
            "documentid": int(row.documentid),
            "link": row.link,
            "intended_for": row.intended_for,
            "method": row.method,
        }
        for row in rows
    ]
    return jsonify({"versions": versions}), HTTPStatus.OK


@bp.get("/get-document")
@bp.get("/get-document/<int:document_id>")
@require_auth
def get_document(document_id: int | None = None):
    """Download document owned by user"""

    if document_id is None:
        document_id = request.args.get("id") or request.args.get("documentid")
        try:
            document_id = int(document_id)
        except (TypeError, ValueError):
            return jsonify({"error": "document id required"}), HTTPStatus.BAD_REQUEST

    try:
        with get_engine().connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, name, path, HEX(sha256) AS sha256_hex, size
                    FROM Documents
                    WHERE id = :id AND ownerid = :uid
                    LIMIT 1
                    """
                ),
                {"id": document_id, "uid": int(g.user["id"])},
            ).first()
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while retrieving document id=%s",
            document_id,
        )
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    if not row:
        return jsonify({"error": "document not found"}), HTTPStatus.NOT_FOUND

    file_path = Path(row.path)
    try:
        file_path.resolve().relative_to(current_app.config["STORAGE_DIR"].resolve())
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "Path safety check failed for document id=%s",
            document_id,
        )
        return jsonify(
            {"error": "document path invalid"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    if not file_path.exists():
        return jsonify(
            {"error": "file missing on disk"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    response = send_file(
        file_path,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=(
            row.name if row.name.lower().endswith(".pdf") else f"{row.name}.pdf"
        ),
        conditional=True,
        max_age=0,
        last_modified=file_path.stat().st_mtime,
    )
    if isinstance(row.sha256_hex, str) and row.sha256_hex:
        response.set_etag(row.sha256_hex.lower())

    response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
    return response


# TODO: Review whether version files should remain accessible without a token.
@bp.get("/get-version/<link>")
def get_version(link: str):
    """Download version with secret link"""

    try:
        with get_engine().connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM Versions
                    WHERE link = :link
                    LIMIT 1
                    """
                ),
                {"link": link},
            ).first()
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while retrieving version link=%s",
            link,
        )
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    if not row:
        return jsonify({"error": "document not found"}), HTTPStatus.NOT_FOUND

    file_path = Path(row.path)
    try:
        file_path.resolve().relative_to(current_app.config["STORAGE_DIR"].resolve())
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "Path safety check failed for version link=%s",
            link,
        )
        return jsonify(
            {"error": "document path invalid"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    if not file_path.exists():
        return jsonify(
            {"error": "file missing on disk"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    response = send_file(
        file_path,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=(
            row.link if row.link.lower().endswith(".pdf") else f"{row.link}.pdf"
        ),
        conditional=True,
        max_age=0,
        last_modified=file_path.stat().st_mtime,
    )
    response.headers["Cache-Control"] = "private, max-age=0"
    return response


@bp.route("/delete-document", methods=["DELETE", "POST"])
@bp.route("/delete-document/<document_id>", methods=["DELETE"])
@require_auth
def delete_document(document_id: int | None = None):
    """Delete document owned by user"""

    if not document_id:
        document_id = (
            request.args.get("id")
            or request.args.get("documentid")
            or (request.is_json and (request.get_json(silent=True) or {}).get("id"))
        )
    try:
        document_id = int(document_id)
    except (TypeError, ValueError):
        return jsonify({"error": "document id required"}), HTTPStatus.BAD_REQUEST

    try:
        with get_engine().connect() as connection:
            row = connection.execute(
                text("SELECT * FROM Documents WHERE id = :id AND ownerid = :uid"),
                {
                    "id": document_id,
                    "uid": int(g.user["id"]),
                },
            ).first()
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while finding document for deletion id=%s",
            document_id,
        )
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    if not row:
        return jsonify({"error": "document not found"}), HTTPStatus.NOT_FOUND

    storage_root = Path(current_app.config["STORAGE_DIR"])
    file_deleted = False
    file_missing = False
    delete_error = None
    try:
        file_path = _safe_resolve_under_storage(row.path, storage_root)
        if file_path.exists():
            try:
                file_path.unlink()
                file_deleted = True
            except Exception:  # pylint: disable=broad-exception-caught
                delete_error = "failed to delete file"
                current_app.logger.exception(
                    "Failed to delete file %s for doc id=%s",
                    file_path,
                    row.id,
                )
        else:
            file_missing = True
    except RuntimeError as error:
        delete_error = str(error)
        current_app.logger.exception(
            "Path safety check failed for doc id=%s",
            row.id,
        )

    try:
        with get_engine().begin() as connection:
            connection.execute(
                text("DELETE FROM Documents WHERE id = :id AND ownerid = :uid"),
                {
                    "id": document_id,
                    "uid": int(g.user["id"]),
                },
            )
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while deleting document id=%s",
            document_id,
        )
        return jsonify(
            {"error": "database error during delete"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    return jsonify(
        {
            "deleted": True,
            "id": document_id,
            "file_deleted": file_deleted,
            "file_missing": file_missing,
            "note": delete_error,
        }
    ), HTTPStatus.OK
