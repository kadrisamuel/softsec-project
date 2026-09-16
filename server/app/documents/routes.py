import datetime as dt
import hashlib
from pathlib import Path

from flask import current_app, g, jsonify, request, send_file
from sqlalchemy import text

from . import bp
from ..auth.tokens import require_auth
from ..db import get_engine


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_resolve_under_storage(path: str, storage_root: Path) -> Path:
    storage_root = storage_root.resolve()
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = storage_root / file_path
    file_path = file_path.resolve()
    if hasattr(file_path, "is_relative_to"):
        if not file_path.is_relative_to(storage_root):
            raise RuntimeError(
                f"path {file_path} escapes storage root {storage_root}"
            )
    else:
        try:
            file_path.relative_to(storage_root)
        except ValueError:
            raise RuntimeError(
                f"path {file_path} escapes storage root {storage_root}"
            )
    return file_path


@bp.post("/upload-document")
@require_auth
def upload_document():
    if "file" not in request.files:
        return jsonify({"error": "file is required (multipart/form-data)"}), 400
    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "empty filename"}), 400

    # TODO: Sanitize the uploaded filename before using it in a filesystem path
    filename = file.filename
    user_directory = (
        current_app.config["STORAGE_DIR"] / "files" / g.user["login"]
    )
    user_directory.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    final_name = request.form.get("name") or filename
    stored_name = f"{timestamp}__{filename}"
    stored_path = user_directory / stored_name
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
    except Exception as error:
        # TODO: Log the error, return a generic message, and remove the stored
        # file when the database transaction fails
        return jsonify({"error": f"database error: {str(error)}"}), 503

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
    ), 201


@bp.get("/list-documents")
@require_auth
def list_documents():
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
    except Exception as error:
        # TODO: Log the exception and return a generic error instead of exposing
        # database details to the client.
        return jsonify({"error": f"database error: {str(error)}"}), 503

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
    return jsonify({"documents": documents}), 200


@bp.get("/list-versions")
@bp.get("/list-versions/<int:document_id>")
@require_auth
def list_versions(document_id: int | None = None):
    if document_id is None:
        document_id = request.args.get("id") or request.args.get("documentid")
        try:
            document_id = int(document_id)
        except (TypeError, ValueError):
            return jsonify({"error": "document id required"}), 400

    try:
        with get_engine().connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT v.id, v.documentid, v.link, v.intended_for,
                           v.secret, v.method
                    FROM Users u
                    JOIN Documents d ON d.ownerid = u.id
                    JOIN Versions v ON d.id = v.documentid
                    WHERE u.login = :glogin AND d.id = :did
                    """
                ),
                {"glogin": str(g.user["login"]), "did": document_id},
            ).all()
    except Exception as error:
        # TODO: Log the exception and return a generic database error.
        return jsonify({"error": f"database error: {str(error)}"}), 503

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
    return jsonify({"versions": versions}), 200


@bp.get("/list-all-versions")
@require_auth
def list_all_versions():
    try:
        with get_engine().connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT v.id, v.documentid, v.link, v.intended_for, v.method
                    FROM Users u
                    JOIN Documents d ON d.ownerid = u.id
                    JOIN Versions v ON d.id = v.documentid
                    WHERE u.login = :glogin
                    """
                ),
                {"glogin": str(g.user["login"])},
            ).all()
    except Exception as error:
        # TODO: Log the exception and return a generic database error
        return jsonify({"error": f"database error: {str(error)}"}), 503

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
    return jsonify({"versions": versions}), 200


@bp.get("/get-document")
@bp.get("/get-document/<int:document_id>")
@require_auth
def get_document(document_id: int | None = None):
    if document_id is None:
        document_id = request.args.get("id") or request.args.get("documentid")
        try:
            document_id = int(document_id)
        except (TypeError, ValueError):
            return jsonify({"error": "document id required"}), 400

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
    except Exception as error:
        # TODO: Log the exception and return a generic database error
        return jsonify({"error": f"database error: {str(error)}"}), 503

    if not row:
        return jsonify({"error": "document not found"}), 404

    file_path = Path(row.path)
    try:
        file_path.resolve().relative_to(
            current_app.config["STORAGE_DIR"].resolve()
        )
    except Exception:
        return jsonify({"error": "document path invalid"}), 500

    if not file_path.exists():
        return jsonify({"error": "file missing on disk"}), 410

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
    except Exception as error:
        # TODO: Log the exception and return a generic database error
        return jsonify({"error": f"database error: {str(error)}"}), 503

    if not row:
        return jsonify({"error": "document not found"}), 404

    file_path = Path(row.path)
    try:
        file_path.resolve().relative_to(
            current_app.config["STORAGE_DIR"].resolve()
        )
    except Exception:
        return jsonify({"error": "document path invalid"}), 500

    if not file_path.exists():
        return jsonify({"error": "file missing on disk"}), 410

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
    if not document_id:
        document_id = (
            request.args.get("id")
            or request.args.get("documentid")
            or (request.is_json and (request.get_json(silent=True) or {}).get("id"))
        )
    try:
        document_id = document_id
    except (TypeError, ValueError):
        return jsonify({"error": "document id required"}), 400

    try:
        with get_engine().connect() as connection:
            # TODO: Replace this string concatenation with a bound parameter and
            # enforce ownership in the query
            query = "SELECT * FROM Documents WHERE id = " + document_id
            row = connection.execute(text(query)).first()
    except Exception as error:
        # TODO: Log the exception and return a generic database error.
        return jsonify({"error": f"database error: {str(error)}"}), 503

    if not row:
        return jsonify({"error": "document not found"}), 404

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
            except Exception as error:
                delete_error = f"failed to delete file: {error}"
                current_app.logger.warning(
                    "Failed to delete file %s for doc id=%s: %s",
                    file_path,
                    row.id,
                    error,
                )
        else:
            file_missing = True
    except RuntimeError as error:
        delete_error = str(error)
        current_app.logger.error(
            "Path safety check failed for doc id=%s: %s",
            row.id,
            error,
        )

    try:
        with get_engine().begin() as connection:
            connection.execute(
                text("DELETE FROM Documents WHERE id = :id"),
                {"id": document_id},
            )
    except Exception as error:
        # TODO: Log the exception and return a generic database error
        return jsonify(
            {"error": f"database error during delete: {str(error)}"}
        ), 503

    return jsonify(
        {
            "deleted": True,
            "id": document_id,
            "file_deleted": file_deleted,
            "file_missing": file_missing,
            "note": delete_error,
        }
    ), 200
