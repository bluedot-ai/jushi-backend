import json
import os

from flask import Flask, g, jsonify, request
try:
    from flask_cors import CORS
except ModuleNotFoundError:
    CORS = None

try:
    from backend.common.auth import parse_token
    from backend.modules.alerts import alerts_bp
    from backend.modules.audits import audits_bp
    from backend.modules.auth.repository import find_user_by_id as find_auth_user_by_id
    from backend.modules.auth import auth_bp
    from backend.modules.cluster import cluster_bp
    from backend.modules.deploy import deploy_bp
    from backend.modules.docs import docs_bp
    from backend.modules.logs import internal_audit_bp, logs_bp
    from backend.modules.logs.constants import DEPLOY_OPERATION_PATHS
    from backend.modules.logs.repository import save_operation_log
    from backend.modules.pods import pods_bp
    from backend.modules.ports import ports_bp
    from backend.modules.resources import resources_bp
    from backend.modules.resources.service import (
        start_accelerator_metric_collector,
        start_resource_snapshot_collector,
        start_resource_trend_cache_refresher,
    )
    from backend.modules.system import system_bp
    from backend.modules.users import users_bp
except ModuleNotFoundError:
    from common.auth import parse_token
    from modules.alerts import alerts_bp
    from modules.audits import audits_bp
    from modules.auth.repository import find_user_by_id as find_auth_user_by_id
    from modules.auth import auth_bp
    from modules.cluster import cluster_bp
    from modules.deploy import deploy_bp
    from modules.docs import docs_bp
    from modules.logs import internal_audit_bp, logs_bp
    from modules.logs.constants import DEPLOY_OPERATION_PATHS
    from modules.logs.repository import save_operation_log
    from modules.pods import pods_bp
    from modules.ports import ports_bp
    from modules.resources import resources_bp
    from modules.resources.service import (
        start_accelerator_metric_collector,
        start_resource_snapshot_collector,
        start_resource_trend_cache_refresher,
    )
    from modules.system import system_bp
    from modules.users import users_bp


AUTH_EXEMPT_PATHS = {
    "/api/system/health",
    "/api/auth/login",
    "/api/internal/audit-events",
    "/api/system/logo",         # GET 免登录，POST/PUT 内部自行校验
    "/api/system/logo/file",    # GET 免登录（返回图片文件）
    "/api/system/logo/enable",  # PUT 内部自行校验管理员
    "/api/system/logo/disable", # PUT 内部自行校验管理员
}
AUTH_EXEMPT_PREFIXES = (
    # 开发阶段放行 Swagger 文档，否则无法先打开页面调登录接口拿 token。
    "/api/docs",
)


def _resolve_docs_port() -> str:
    # 兼容 python app.py 和 flask run 两种启动方式，尽量打印正确的 Swagger 端口。
    if os.getenv("FLASK_RUN_PORT"):
        return os.getenv("FLASK_RUN_PORT", "")
    if os.getenv("PORT"):
        return os.getenv("PORT", "")
    if os.getenv("FLASK_RUN_FROM_CLI") == "true":
        return "5000"
    return "8080"


def _is_auth_exempt(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    if normalized in AUTH_EXEMPT_PATHS:
        return True
    return any(normalized.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES)


def _register_auth_interceptor(app: Flask) -> None:
    @app.before_request
    def auth_interceptor():
        # 统一拦截 /api/*，只放行登录、健康检查和开发文档。
        if request.method == "OPTIONS":
            return None
        if not request.path.startswith("/api/"):
            return None
        if _is_auth_exempt(request.path):
            return None

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"is_success": False, "msg": "未登录"}), 401

        token = auth_header.removeprefix("Bearer ").strip()
        if not token:
            return jsonify({"is_success": False, "msg": "未登录"}), 401

        payload, error = parse_token(token)
        if error:
            return jsonify({"is_success": False, "msg": error}), 401

        user = find_auth_user_by_id(payload["id"])
        if not user:
            return jsonify({"is_success": False, "msg": "用户不存在"}), 401
        if user.get("status") != "active":
            return jsonify({"is_success": False, "msg": "用户已被禁用"}), 403

        g.auth_token = token
        g.current_user = user
        return None


def _register_log_middleware(app: Flask) -> None:
    @app.after_request
    def log_deploy_operations(response):
        if request.method != "POST":
            return response
        operation_type = DEPLOY_OPERATION_PATHS.get(request.path)
        if not operation_type:
            return response

        try:
            req_body = request.get_json(silent=True) or {}
            resp_body = response.get_json(silent=True) or {}
            content = req_body.get("content") or {}

            if operation_type == "check_available":
                devices = content.get("devices") or {}
                target_name = str(list(devices.keys())[0]) if devices else ""
            elif operation_type == "create":
                resp_content = resp_body.get("content") or {}
                target_name = str(resp_content.get("deployment_name", ""))
            elif operation_type in ("retrieve", "release", "reset"):
                target_name = str(content.get("name", ""))
            elif operation_type == "list":
                target_name = "all"
            else:
                target_name = ""

            is_success = response.status_code < 400
            error_message = ""
            if not is_success:
                error_message = str(resp_body.get("msg", "") or resp_body.get("message", "") or "")

            xff = request.headers.get("X-Forwarded-For", "")
            if xff:
                operator_ip = xff.split(",")[0].strip()
            else:
                operator_ip = request.headers.get("X-Real-IP", "").strip() or (request.remote_addr or "")

            operator = "anonymous"
            if hasattr(g, "current_user") and g.current_user:
                operator = str(g.current_user.get("username") or "anonymous")

            save_operation_log({
                "operation_type": operation_type,
                "operator": operator,
                "operator_ip": operator_ip,
                "target_type": "deploy",
                "target_name": target_name,
                "request_payload": json.dumps(req_body, ensure_ascii=False),
                "response_payload": json.dumps(resp_body, ensure_ascii=False),
                "http_status_code": response.status_code,
                "is_success": is_success,
                "error_message": error_message,
            })
        except Exception:
            pass
        return response


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
        static_url_path="/static",
    )
    # 开发联调阶段允许 Swagger UI、Vite 前端等跨域请求后端 API。
    if CORS:
        CORS(app, resources={r"/api/*": {"origins": "*"}})
    else:
        @app.after_request
        def add_cors_headers(response):
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-User, X-Audit-Key"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            return response

    _register_auth_interceptor(app)
    _register_log_middleware(app)

    # 按业务域注册接口模块；根路径 "/" 暂不占用，后续留给前端或网关。
    app.register_blueprint(system_bp, url_prefix="/api/system")
    app.register_blueprint(docs_bp, url_prefix="/api/docs")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(users_bp, url_prefix="/api/users")
    app.register_blueprint(cluster_bp)
    app.register_blueprint(deploy_bp, url_prefix="/api/deploy")
    app.register_blueprint(ports_bp, url_prefix="/api/port-list")
    app.register_blueprint(resources_bp, url_prefix="/api/resources")
    app.register_blueprint(pods_bp, url_prefix="/api/pods")
    app.register_blueprint(alerts_bp, url_prefix="/api/alerts")
    app.register_blueprint(logs_bp, url_prefix="/api/logs")
    app.register_blueprint(internal_audit_bp, url_prefix="/api/internal")
    app.register_blueprint(audits_bp, url_prefix="/api/audits")

    docs_port = _resolve_docs_port()
    print(f"[Jushi] Swagger UI: http://127.0.0.1:{docs_port}/api/docs")
    print(f"[Jushi] OpenAPI JSON: http://127.0.0.1:{docs_port}/api/docs/openapi.json")
    if start_resource_snapshot_collector():
        print("[Jushi] Resource snapshot collector: started")
    if start_resource_trend_cache_refresher():
        print("[Jushi] Resource trend cache refresher: started")
    if start_accelerator_metric_collector():
        print("[Jushi] Accelerator history collector: started")

    return app


app = create_app()


if __name__ == "__main__":
    debug_enabled = os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    app.run(host="0.0.0.0", port=8080, debug=debug_enabled, use_reloader=False)

