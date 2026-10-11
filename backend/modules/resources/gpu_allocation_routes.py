"""Read-only GPU analytics and explicitly authorized manual collection."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, g, jsonify, request

from . import gpu_allocation_collector, gpu_allocation_stats
from .response import _error, _ok


gpu_allocation_bp = Blueprint("gpu_allocation", __name__)
gpu_allocation_internal_bp = Blueprint("gpu_allocation_internal", __name__)
_SHANGHAI = timezone(timedelta(hours=8))
_logger = logging.getLogger(__name__)


def _json_value(value):
    if isinstance(value, datetime):
        value = value.replace(tzinfo=_SHANGHAI) if value.tzinfo is None else value.astimezone(_SHANGHAI)
        return value.isoformat(timespec="seconds")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _respond(payload):
    status = 200 if payload.get("is_success") else payload.get("http_status_code", 500)
    return jsonify(_json_value(payload)), status


@gpu_allocation_bp.get("/current")
def current():
    # This endpoint never persists a snapshot: opening the UI is not collection.
    vendor = (request.args.get("vendor") or "all").strip()
    if vendor not in {"all", "nvidia", "ascend"}:
        return _respond(_error("vendor 仅支持 all、nvidia 或 ascend", 400))
    try:
        snapshot, diagnostics = gpu_allocation_collector.build_current_snapshot(vendor=vendor, include_observations=True)
        return _respond(_ok({"data": {**snapshot, "diagnostics": diagnostics}}))
    except Exception:
        _logger.exception("GPU allocation current query failed")
        return _respond(_error("GPU 资源查询失败，请检查数据源和后台日志", 503))


@gpu_allocation_bp.get("/trend")
def trend():
    return _respond(gpu_allocation_stats.trend(request.args.to_dict()))


@gpu_allocation_bp.get("/compare")
def compare():
    return _respond(gpu_allocation_stats.compare(request.args.to_dict()))


@gpu_allocation_internal_bp.post("/collect")
def collect():
    user = getattr(g, "current_user", None)
    if not user:
        return _respond(_error("未登录", 401))
    if user.get("role") != "admin":
        return _respond(_error("仅管理员可手动采集 GPU 历史快照", 403))
    # Do not accept cluster, timestamps or metrics supplied by the browser.
    try:
        result = gpu_allocation_collector.collect_and_save_once()
        if result.get("save_error"):
            return _respond(_error("GPU 历史快照写入失败，请检查迁移和数据库连接", 503))
        return _respond(_ok({"data": result}))
    except Exception:
        _logger.exception("GPU allocation manual collection failed")
        return _respond(_error("GPU 历史采集失败，请检查后台日志", 503))
