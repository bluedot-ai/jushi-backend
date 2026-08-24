from flask import Blueprint, jsonify, request

from . import service
from .schema import normalize_resource_query


resources_bp = Blueprint("resources", __name__)

# 资源中心对外接口统一挂在 /api/resources 下。
# 这些接口大多不直接查本地数据库，而是进入 service.py 后调用 PaaS / Kubernetes 现有接口，
# 再转换成前端资源大盘、节点列表、显卡列表和趋势图需要的产品化字段。


@resources_bp.get("/summary")
def summary():
    # 首页 / 资源中心顶部资源总览：节点数、物理 GPU、vGPU、显存、算力和健康度。
    return jsonify(service.summary(normalize_resource_query(request.args)))


@resources_bp.get("/nodes")
def nodes():
    # 节点资源列表：逐节点展示资源分配率，前端资源中心和首页节点明细都会用。
    return jsonify(service.nodes(normalize_resource_query(request.args)))


@resources_bp.get("/nodes/<node_name>/gpus")
def node_gpus(node_name):
    # Ready、可调度节点的真实物理 GPU/NPU 单卡实时指标。
    return jsonify(service.node_gpus(node_name, normalize_resource_query(request.args)))


@resources_bp.get("/nodes/<node_name>/gpu-trend")
def node_gpu_trend(node_name):
    # 按稳定物理卡标识返回计算利用率或显存利用率历史矩阵。
    return jsonify(service.node_gpu_trend(node_name, normalize_resource_query(request.args)))


@resources_bp.get("/gpus")
def gpus():
    # GPU / vGPU / 显存 / 算力资源统计：按资源名和显卡型号做聚合。
    return jsonify(service.gpus(normalize_resource_query(request.args)))


@resources_bp.get("/quotas")
def quotas():
    # 命名空间资源配额：查 Kubernetes ResourceQuota，无权限时后端会降级为空列表。
    return jsonify(service.quotas(normalize_resource_query(request.args)))


@resources_bp.get("/cards")
def cards():
    # 显卡 / vGPU 卡片列表：当前是根据节点资源推导出来的卡片视图，不是真实 GPU UUID。
    return jsonify(service.cards(normalize_resource_query(request.args)))


@resources_bp.get("/trend")
def trend():
    # 资源趋势数据：优先读 MySQL resource_snapshot，历史不足时用当前 summary 兜底。
    return jsonify(service.trend(normalize_resource_query(request.args)))


@resources_bp.get("/recommendation")
def recommendation():
    # 首页资源推荐策略：根据节点资源分配率给出推荐节点和风险提示，不直接参与调度。
    return jsonify(service.recommendation(normalize_resource_query(request.args)))

