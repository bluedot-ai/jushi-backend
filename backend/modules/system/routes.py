import os

from flask import Blueprint, g, jsonify, request

from . import service
from .algorithm_version import get_algorithm_version
from .schema import LOGO_MAX_SIZE_BYTES, validate_logo_file

system_bp = Blueprint("system", __name__)


@system_bp.get("/health")
def health():
    """健康检查接口，供本地调试、Docker Compose 和部署探针使用。"""
    return jsonify({"status": "ok"})


@system_bp.get("/algorithm-version")
def algorithm_version():
    """读取宿主机算法目录中的版本标识文件名。"""
    return jsonify(get_algorithm_version())


@system_bp.get("/logo")
def get_logo():
    """获取当前系统 logo 状态（免登录），包含 URL 和启用标记。"""
    return jsonify(service.get_logo())


@system_bp.post("/logo")
def upload_logo():
    """上传/更换系统 logo（需登录 + 管理员权限），自动启用。

    因为 GET /api/system/logo 需要免登录供登录页使用，
    而该路径被全局认证拦截器放行，因此 POST 在此手动校验身份。
    """
    user = _resolve_current_user()
    if not user:
        return jsonify({"is_success": False, "msg": "未登录"}), 401

    if user.get("role") != "admin":
        return jsonify({"is_success": False, "msg": "仅管理员可更换 Logo"}), 403

    if "logo" not in request.files:
        return jsonify({"is_success": False, "msg": "请选择文件"}), 400

    file = request.files["logo"]
    error, ext = validate_logo_file(file)
    if error:
        return jsonify({"is_success": False, "msg": error}), 400

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > LOGO_MAX_SIZE_BYTES:
        return jsonify(
            {"is_success": False, "msg": f"文件过大，最大 {LOGO_MAX_SIZE_BYTES // (1024 * 1024)} MB"}
        ), 400

    return service.upload_logo(file)


@system_bp.put("/logo/enable")
def enable_logo():
    """启用自定义 Logo（需管理员，不删除文件仅切换显示）。

    该路径在认证豁免列表中，由路由内部手动校验身份。
    """
    user = _resolve_current_user()
    if not user:
        return jsonify({"is_success": False, "msg": "未登录"}), 401
    if user.get("role") != "admin":
        return jsonify({"is_success": False, "msg": "仅管理员可操作"}), 403
    return jsonify(service.set_logo_enabled(True))


@system_bp.put("/logo/disable")
def disable_logo():
    """恢复默认 Logo（需管理员，关掉自定义开关，文件全部保留）。

    该路径在认证豁免列表中，由路由内部手动校验身份。
    """
    user = _resolve_current_user()
    if not user:
        return jsonify({"is_success": False, "msg": "未登录"}), 401
    if user.get("role") != "admin":
        return jsonify({"is_success": False, "msg": "仅管理员可操作"}), 403
    return jsonify(service.set_logo_enabled(False))


@system_bp.get("/logo/file")
def serve_logo_file():
    """直接返回 logo 图片文件（免登录），供 <img> 标签使用。

    仅在 logo 启用时返回文件，否则 404。
    """
    from flask import send_file

    file_path = service.get_logo_file_path()
    if not file_path:
        return jsonify({"is_success": False, "msg": "Logo 未启用或文件不存在"}), 404

    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".gif": "image/gif"}
    return send_file(file_path, mimetype=mime_map.get(ext, "image/png"))


def _resolve_current_user() -> dict | None:
    """在认证豁免路径上手动解析当前用户。"""
    if hasattr(g, "current_user") and g.current_user:
        return g.current_user

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        x_user = (request.headers.get("X-User") or "").strip()
        if x_user:
            return _lookup_user(x_user)
        return None

    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return None

    try:
        from backend.common.auth import parse_token
        from backend.modules.auth.repository import find_user_by_id
    except ModuleNotFoundError:
        from common.auth import parse_token
        from modules.auth.repository import find_user_by_id

    payload, error = parse_token(token)
    if error:
        return None

    return find_user_by_id(payload["id"])


def _lookup_user(username: str) -> dict | None:
    """通过用户名查找用户（开发阶段 fallback）。"""
    try:
        from backend.modules.auth.repository import find_user_by_username
    except ModuleNotFoundError:
        from modules.auth.repository import find_user_by_username
    return find_user_by_username(username)

