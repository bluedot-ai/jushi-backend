import hmac
import logging

from flask import Blueprint, jsonify, request

from . import service
from .schema import normalize_legacy_audit_event

try:
    from backend.config import Config
except ModuleNotFoundError:
    from config import Config


internal_audit_bp = Blueprint("internal_audit", __name__)
logger = logging.getLogger(__name__)


@internal_audit_bp.post("/audit-events")
def ingest_audit_event():
    configured_key = Config.AUDIT_INGEST_KEY
    if not configured_key:
        return jsonify({
            "is_success": False,
            "msg": "audit ingest is disabled",
        }), 503

    supplied_key = request.headers.get("X-Audit-Key", "")
    if not supplied_key or not hmac.compare_digest(supplied_key, configured_key):
        return jsonify({
            "is_success": False,
            "msg": "invalid audit ingest key",
        }), 401

    if request.content_length and request.content_length > Config.AUDIT_INGEST_MAX_BYTES:
        return jsonify({
            "is_success": False,
            "msg": "audit event payload is too large",
        }), 413

    event, error = normalize_legacy_audit_event(request.get_json(silent=True))
    if error:
        return jsonify({"is_success": False, "msg": error}), 400

    try:
        result = service.ingest_legacy_audit_event(event)
    except Exception:
        logger.exception("Failed to persist legacy audit event")
        return jsonify({
            "is_success": False,
            "msg": "failed to persist audit event",
        }), 500

    duplicate = bool(result.get("duplicate"))
    return jsonify({
        "is_success": True,
        "duplicate": duplicate,
    }), 200 if duplicate else 201

