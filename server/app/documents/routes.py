from flask import g, jsonify
from sqlalchemy import text

from . import bp
from ..auth.tokens import require_auth
from ..db import get_engine


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
