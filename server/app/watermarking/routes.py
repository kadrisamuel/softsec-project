import hashlib
import pickle as standard_pickle
from pathlib import Path

try:
    import dill as plugin_pickle
except Exception:
    plugin_pickle = standard_pickle

from flask import current_app, jsonify, request
from sqlalchemy import text
from werkzeug.utils import secure_filename

import watermarking_utils as watermarking_utils
from watermarking_method import WatermarkingMethod

from . import bp
from ..auth.tokens import require_auth
from ..db import get_engine


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
        return jsonify({"error": "document id required"}), 400

    payload = request.get_json(silent=True) or {}
    method = payload.get("method")
    intended_for = payload.get("intended_for")
    position = payload.get("position") or None
    secret = payload.get("secret")
    key = payload.get("key")

    try:
        document_id = int(document_id)
    except (TypeError, ValueError):
        return jsonify({"error": "document_id (int) is required"}), 400
    if (
        not method
        or not intended_for
        or not isinstance(secret, str)
        or not isinstance(key, str)
    ):
        return jsonify(
            {"error": "method, intended_for, secret, and key are required"}
        ), 400

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
    except Exception as error:
        # TODO: Log the exception and return a generic db error
        return jsonify({"error": f"database error: {str(error)}"}), 503

    if not row:
        return jsonify({"error": "document not found"}), 404

    storage_root = Path(current_app.config["STORAGE_DIR"]).resolve()
    file_path = Path(row.path)
    if not file_path.is_absolute():
        file_path = storage_root / file_path
    file_path = file_path.resolve()
    try:
        file_path.relative_to(storage_root)
    except ValueError:
        return jsonify({"error": "document path invalid"}), 500
    if not file_path.exists():
        return jsonify({"error": "file missing on disk"}), 410

    try:
        applicable = watermarking_utils.is_watermarking_applicable(
            method=method,
            pdf=str(file_path),
            position=position,
        )
        if applicable is False:
            return jsonify({"error": "watermarking method not applicable"}), 400
    except Exception as error:
        return jsonify(
            {"error": f"watermark applicability check failed: {error}"}
        ), 400

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
            return jsonify({"error": "watermarking produced no output"}), 500
    except Exception as error:
        return jsonify({"error": f"watermarking failed: {error}"}), 500

    base_name = Path(row.name or file_path.name).stem
    intended_slug = secure_filename(intended_for)
    destination_directory = file_path.parent / "watermarks"
    destination_directory.mkdir(parents=True, exist_ok=True)

    filename = f"{base_name}__{intended_slug}.pdf"
    destination_path = destination_directory / filename
    try:
        with destination_path.open("wb") as file:
            file.write(watermarked_bytes)
    except Exception as error:
        return jsonify(
            {"error": f"failed to write watermarked file: {error}"}
        ), 500

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
    except Exception as error:
        try:
            destination_path.unlink(missing_ok=True)
        except Exception:
            pass
        # TODO: Log the exception and return a generic db error
        return jsonify(
            {"error": f"database error during version insert: {error}"}
        ), 503

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
    ), 201


@bp.post("/load-plugin")
@require_auth
def load_plugin():
    payload = request.get_json(silent=True) or {}
    filename = (payload.get("filename") or "").strip()
    overwrite = bool(payload.get("overwrite", False)) #unused

    if not filename:
        return jsonify({"error": "filename is required"}), 400

    storage_root = Path(current_app.config["STORAGE_DIR"])
    plugins_directory = storage_root / "files" / "plugins"
    try:
        plugins_directory.mkdir(parents=True, exist_ok=True)
        plugin_path = plugins_directory / filename
    except Exception as error:
        return jsonify({"error": f"plugin path error: {error}"}), 500

    # TODO: Prevent path traversal and replace unsafe pickle/dill loading with a
    # trusted plugin installation mechanism
    if not plugin_path.exists():
        # TODO: Replace the undefined `safe` value with a sanitized filename
        return jsonify({"error": f"plugin file not found: {safe}"}), 404

    try:
        with plugin_path.open("rb") as file:
            plugin = plugin_pickle.load(file)
    except Exception as error:
        return jsonify({"error": f"failed to deserialize plugin: {error}"}), 400

    if isinstance(plugin, type):
        plugin_class = plugin
    else:
        plugin_class = plugin.__class__

    method_name = getattr(
        plugin_class,
        "name",
        getattr(plugin_class, "__name__", None),
    )
    if not method_name or not isinstance(method_name, str):
        return jsonify(
            {"error": "plugin class must define a readable name (class.__name__ or .name)"}
        ), 400

    has_api = all(
        hasattr(plugin_class, attribute)
        for attribute in ("add_watermark", "read_secret")
    )
    if WatermarkingMethod is not None:
        is_valid = issubclass(plugin_class, WatermarkingMethod) and has_api
    else:
        is_valid = has_api
    if not is_valid:
        return jsonify(
            {
                "error": (
                    "plugin does not implement WatermarkingMethod API "
                    "(add_watermark/read_secret)"
                )
            }
        ), 400

    watermarking_utils.METHODS[method_name] = plugin_class()
    return jsonify(
        {
            "loaded": True,
            "filename": filename,
            "registered_as": method_name,
            "class_qualname": (
                f"{getattr(plugin_class, '__module__', '?')}."
                f"{getattr(plugin_class, '__qualname__', plugin_class.__name__)}"
            ),
            "methods_count": len(watermarking_utils.METHODS),
        }
    ), 201


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
    return jsonify({"methods": methods, "count": len(methods)}), 200


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
        return jsonify({"error": "document id required"}), 400

    payload = request.get_json(silent=True) or {}
    method = payload.get("method")
    position = payload.get("position") or None
    key = payload.get("key")

    try:
        document_id = int(document_id)
    except (TypeError, ValueError):
        return jsonify({"error": "document_id (int) is required"}), 400
    if not method or not isinstance(key, str):
        return jsonify({"error": "method, and key are required"}), 400

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
    except Exception as error:
        # TODO: Log the exception and return a generic db error
        return jsonify({"error": f"database error: {str(error)}"}), 503

    if not row:
        return jsonify({"error": "document not found"}), 404

    storage_root = Path(current_app.config["STORAGE_DIR"]).resolve()
    file_path = Path(row.path)
    if not file_path.is_absolute():
        file_path = storage_root / file_path
    file_path = file_path.resolve()
    try:
        file_path.relative_to(storage_root)
    except ValueError:
        return jsonify({"error": "document path invalid"}), 500
    if not file_path.exists():
        return jsonify({"error": "file missing on disk"}), 410

    try:
        secret = watermarking_utils.read_watermark(
            method=method,
            pdf=str(file_path),
            key=key,
        )
    except Exception as error:
        return jsonify(
            {"error": f"Error when attempting to read watermark: {error}"}
        ), 400

    return jsonify(
        {
            "documentid": document_id,
            "secret": secret,
            "method": method,
            "position": position,
        }
    ), 201
