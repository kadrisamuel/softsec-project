import hashlib
from http import HTTPStatus
from pathlib import Path

from flask import current_app, jsonify, request
from sqlalchemy import text
from werkzeug.utils import secure_filename

from ..auth.tokens import require_auth
from ..db import get_engine
from . import bp
from . import utils as watermarking_utils
from .method import WatermarkingError


@bp.post("/create-watermark")
@bp.post("/create-watermark/<int:document_id>")
@require_auth
def create_watermark(document_id: int | None = None):
    if not document_id:
        document_id = (
            request.args.get("id")
            or request.args.get("documentid")
            or (request.is_json and (request.get_json(silent=True) or {}).get("id"))
        )
    try:
        document_id = document_id
    except (TypeError, ValueError):
        return jsonify({"error": "document id required"}), HTTPStatus.BAD_REQUEST

    payload = request.get_json(silent=True) or {}
    method = payload.get("method")
    intended_for = payload.get("intended_for")
    position = payload.get("position") or None
    secret = payload.get("secret")
    key = payload.get("key")

    try:
        document_id = int(document_id)
    except (TypeError, ValueError):
        return jsonify(
            {"error": "document_id (int) is required"}
        ), HTTPStatus.BAD_REQUEST
    if (
        not method
        or not intended_for
        or not isinstance(secret, str)
        or not isinstance(key, str)
    ):
        return jsonify(
            {"error": "method, intended_for, secret, and key are required"}
        ), HTTPStatus.BAD_REQUEST

    try:
        with get_engine().connect() as connection:
            # TODO: Enforce document ownership in this query
            row = connection.execute(
                text(
                    """
                    SELECT id, name, path
                    FROM Documents
                    WHERE id = :id
                    LIMIT 1
                    """
                ),
                {"id": document_id},
            ).first()
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception("DB error during watermark creation")
        return jsonify(
            {"error": "Watermark creation failed"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    if not row:
        return jsonify({"error": "document not found"}), HTTPStatus.NOT_FOUND

    storage_root = Path(current_app.config["STORAGE_DIR"]).resolve()
    file_path = Path(row.path)
    if not file_path.is_absolute():
        file_path = storage_root / file_path
    file_path = file_path.resolve()
    try:
        file_path.relative_to(storage_root)
    except ValueError:
        current_app.logger.exception(
            "Path safety check failed during watermark creation for document id=%s",
            document_id,
        )
        return jsonify(
            {"error": "document path invalid"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR
    if not file_path.exists():
        return jsonify(
            {"error": "file missing on disk"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    try:
        applicable = watermarking_utils.is_watermarking_applicable(
            method=method,
            pdf=str(file_path),
            position=position,
        )
        if applicable is False:
            return jsonify(
                {"error": "watermarking method not applicable"}
            ), HTTPStatus.BAD_REQUEST
    except KeyError:
        return jsonify({"error": "unknown watermarking method"}), HTTPStatus.BAD_REQUEST
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "Watermark applicability check failed for document id=%s",
            document_id,
        )
        return jsonify(
            {"error": "watermark applicability check failed"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    try:
        watermarked_bytes = watermarking_utils.apply_watermark(
            pdf=str(file_path),
            secret=secret,
            key=key,
            method=method,
            position=position,
        )
        if (
            not isinstance(watermarked_bytes, (bytes, bytearray))
            or len(watermarked_bytes) == 0
        ):
            return jsonify(
                {"error": "watermarking produced no output"}
            ), HTTPStatus.INTERNAL_SERVER_ERROR
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "Watermark creation failed for document id=%s",
            document_id,
        )
        return jsonify(
            {"error": "watermarking failed"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    base_name = Path(row.name or file_path.name).stem
    intended_slug = secure_filename(intended_for)
    destination_directory = file_path.parent / "watermarks"
    destination_directory.mkdir(parents=True, exist_ok=True)

    filename = f"{base_name}__{intended_slug}.pdf"
    destination_path = destination_directory / filename
    try:
        with destination_path.open("wb") as file:
            file.write(watermarked_bytes)
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "Failed to write watermarked file for document id=%s",
            document_id,
        )
        return jsonify(
            {"error": "failed to write watermarked file"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    link = hashlib.sha1(filename.encode("utf-8")).hexdigest()
    try:
        with get_engine().begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO Versions
                        (documentid, link, intended_for, secret, method, position, path)
                    VALUES
                        (:documentid, :link, :intended_for, :secret, :method,
                         :position, :path)
                    """
                ),
                {
                    "documentid": document_id,
                    "link": link,
                    "intended_for": intended_for,
                    "secret": secret,
                    "method": method,
                    "position": position or "",
                    "path": destination_path,
                },
            )
            version_id = int(
                connection.execute(text("SELECT LAST_INSERT_ID()")).scalar()
            )
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while inserting watermark version for document id=%s",
            document_id,
        )
        try:
            destination_path.unlink(missing_ok=True)
        except Exception:  # pylint: disable=broad-exception-caught
            current_app.logger.exception(
                "Failed to remove watermarked file after DB error: %s",
                destination_path,
            )
        return jsonify(
            {"error": f"database error during version insert"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    return jsonify(
        {
            "id": version_id,
            "documentid": document_id,
            "link": link,
            "intended_for": intended_for,
            "method": method,
            "position": position,
            "filename": filename,
            "size": len(watermarked_bytes),
        }
    ), HTTPStatus.CREATED


@bp.get("/get-watermarking-methods")
def get_watermarking_methods():
    methods = []
    for method in watermarking_utils.METHODS:
        methods.append(
            {
                "name": method,
                "description": watermarking_utils.get_method(method).get_usage(),
            }
        )
    return jsonify({"methods": methods, "count": len(methods)}), HTTPStatus.OK


@bp.post("/read-watermark")
@bp.post("/read-watermark/<int:document_id>")
@require_auth
def read_watermark(document_id: int | None = None):
    if not document_id:
        document_id = (
            request.args.get("id")
            or request.args.get("documentid")
            or (request.is_json and (request.get_json(silent=True) or {}).get("id"))
        )
    try:
        document_id = document_id
    except (TypeError, ValueError):
        return jsonify({"error": "document id required"}), HTTPStatus.BAD_REQUEST

    payload = request.get_json(silent=True) or {}
    method = payload.get("method")
    position = payload.get("position") or None
    key = payload.get("key")

    try:
        document_id = int(document_id)
    except (TypeError, ValueError):
        return jsonify(
            {"error": "document_id (int) is required"}
        ), HTTPStatus.BAD_REQUEST
    if not method or not isinstance(key, str):
        return jsonify(
            {"error": "method, and key are required"}
        ), HTTPStatus.BAD_REQUEST

    try:
        with get_engine().connect() as connection:
            # TODO: Enforce document ownership in this query
            row = connection.execute(
                text(
                    """
                    SELECT id, name, path
                    FROM Documents
                    WHERE id = :id
                    """
                ),
                {"id": document_id},
            ).first()
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while retrieving document for watermark read id=%s",
            document_id,
        )
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    if not row:
        return jsonify({"error": "document not found"}), HTTPStatus.NOT_FOUND

    storage_root = Path(current_app.config["STORAGE_DIR"]).resolve()
    file_path = Path(row.path)
    if not file_path.is_absolute():
        file_path = storage_root / file_path
    file_path = file_path.resolve()
    try:
        file_path.relative_to(storage_root)
    except ValueError:
        current_app.logger.exception(
            "Path safety check failed during watermark read for document id=%s",
            document_id,
        )
        return jsonify(
            {"error": "document path invalid"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR
    if not file_path.exists():
        return jsonify(
            {"error": "file missing on disk"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    try:
        secret = watermarking_utils.read_watermark(
            method=method,
            pdf=str(file_path),
            key=key,
        )
    except (KeyError, ValueError, WatermarkingError):
        return jsonify(
            {"error": "Error when attempting to read watermark"}
        ), HTTPStatus.BAD_REQUEST
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "Unexpected error while reading watermark for document id=%s",
            document_id,
        )
        return jsonify(
            {"error": "Error when attempting to read watermark"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    return jsonify(
        {
            "documentid": document_id,
            "secret": secret,
            "method": method,
            "position": position,
        }
    ), HTTPStatus.OK
