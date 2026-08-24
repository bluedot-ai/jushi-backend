from flask import Blueprint, jsonify, request

from . import service
from .schema import (
    normalize_alert_action,
    normalize_alert_create,
    normalize_alert_history_query,
    normalize_alert_query,
)


alerts_bp = Blueprint("alerts", __name__)


@alerts_bp.post("/list")
def list_alerts():
    # 查询告警列表，后续接入 alert_event 表和筛选条件。
    payload = request.get_json(silent=True) or {}
    return jsonify(service.list_alerts(normalize_alert_query(payload)))


@alerts_bp.post("/history")
def list_alert_history():
    payload = request.get_json(silent=True) or {}
    return jsonify(service.list_alert_history(normalize_alert_history_query(payload)))


@alerts_bp.post("/create")
def create_alert():
    # 创建告警事件，主要供资源不足、Pod 异常等后端流程写入。
    payload = request.get_json(silent=True) or {}
    return jsonify(service.create_alert(normalize_alert_create(payload)))


@alerts_bp.post("/resolve")
def resolve_alert():
    # 标记告警已解决，记录处理人和解决时间。
    payload = request.get_json(silent=True) or {}
    return jsonify(service.resolve_alert(normalize_alert_action(payload)))


@alerts_bp.post("/ignore")
def ignore_alert():
    # 忽略无需处理的告警，避免它继续出现在待处理列表中。
    payload = request.get_json(silent=True) or {}
    return jsonify(service.ignore_alert(normalize_alert_action(payload)))


@alerts_bp.post("/reopen")
def reopen_alert():
    payload = request.get_json(silent=True) or {}
    return jsonify(service.reopen_alert(normalize_alert_action(payload)))
