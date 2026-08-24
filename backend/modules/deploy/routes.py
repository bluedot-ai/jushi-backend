from flask import Blueprint, Response, jsonify, request

from . import service


deploy_bp = Blueprint("deploy", __name__)


@deploy_bp.post("/check-available")
def check_available():
    # 资源预检接口：后续迁移 app_x86_195.py/app_arm_195.py 中的 GPU 余量、CPU/内存和端口避让检查。
    payload = request.get_json(silent=True) or {}
    result = service.check_available(payload)
    return jsonify(result), result.get("http_status_code", 200)


@deploy_bp.post("/create-default")
def create_default():
    # 创建推理实例：后续生成 PaaS Deployment + NodePort Service，并把创建结果写入 deploy_instance。
    payload = request.get_json(silent=True) or {}
    result, status_code = service.create_default(payload)
    return jsonify(result), status_code


@deploy_bp.post("/retrieve")
def retrieve():
    # 查询单个部署详情：合并 PaaS Deployment 详情和 Pod 状态，供实例中心查看。
    payload = request.get_json(silent=True) or {}
    result, status_code = service.retrieve(payload)
    return jsonify(result), status_code


@deploy_bp.post("/release")
def release():
    # 释放部署资源：后续删除 PaaS Deployment 和 Service，并更新实例状态。
    payload = request.get_json(silent=True) or {}
    result = service.release(payload)
    return jsonify(result), result.get("http_status_code", 200)


@deploy_bp.post("/reset")
def reset():
    # 重启部署实例：后续复用 PaaS/Kubernetes restart 能力。
    payload = request.get_json(silent=True) or {}
    result = service.reset(payload)
    return jsonify(result), result.get("http_status_code", 200)


@deploy_bp.post("/stop")
def stop():
    # 停止部署语义待确认，先统一 envelope 校验，避免前端绕过部署类流水规则。
    payload = request.get_json(silent=True) or {}
    result = service.stop(payload)
    return jsonify(result), result.get("http_status_code", 200)


@deploy_bp.post("/logs")
def logs():
    # 部署排查输出按纯文本返回，方便 Swagger 和前端直接保留 kubectl describe 的换行格式。
    payload = request.get_json(silent=True) or {}
    result = service.logs(payload)
    status_code = result.get("http_status_code", 200)
    describe = ((result.get("content") or {}).get("describe") or "")
    if 200 <= status_code < 300:
        return Response(describe, status=status_code, mimetype="text/plain; charset=utf-8")
    return jsonify(result), status_code


@deploy_bp.post("/list")
def list_deployments():
    # 查询部署列表，实例中心页面会优先使用这个接口。
    payload = request.get_json(silent=True) or {}
    result = service.list_deployments(payload)
    return jsonify(result), result.get("http_status_code", 200)
