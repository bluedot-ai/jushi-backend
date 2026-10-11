from .alerts import ALERT_PATHS
from .audits import AUDIT_PATHS
from .auth import AUTH_PATHS
from .cluster import CLUSTER_PATHS
from .components import COMPONENTS
from .deploy import DEPLOY_PATHS
from .gpu_allocation import GPU_ALLOCATION_PATHS
from .logs import LOG_PATHS
from .pods import POD_PATHS
from .ports import PORT_PATHS
from .resources import RESOURCE_PATHS
from .system import SYSTEM_PATHS
from .users import USER_PATHS


TAGS = [
    {"name": "System", "description": "系统健康检查"},
    {"name": "Auth", "description": "登录与当前用户"},
    {"name": "Users", "description": "用户管理"},
    {"name": "Cluster", "description": "集群查询"},
    {"name": "Deploy", "description": "推理部署生命周期"},
    {"name": "Ports", "description": "封闭端口 / 端口避让"},
    {"name": "Resources", "description": "集群资源"},
    {"name": "Pods", "description": "Pod 查询与操作"},
    {"name": "Alerts", "description": "告警"},
    {"name": "Audits", "description": "操作审计"},
    {"name": "Logs", "description": "日志"},
]


def build_openapi_spec() -> dict:
    paths = {}
    for section_paths in (
        SYSTEM_PATHS,
        AUTH_PATHS,
        USER_PATHS,
        CLUSTER_PATHS,
        DEPLOY_PATHS,
        PORT_PATHS,
        RESOURCE_PATHS,
        GPU_ALLOCATION_PATHS,
        POD_PATHS,
        ALERT_PATHS,
        AUDIT_PATHS,
        LOG_PATHS,
    ):
        paths.update(section_paths)

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "聚时 AI 推理资源管理平台 API",
            "version": "0.1.0",
            "description": "一期开发接口调试文档，覆盖用户、部署、端口、资源、Pod、告警、审计和日志接口。",
        },
        "servers": [
            {"url": "/", "description": "Current host"},
        ],
        "tags": TAGS,
        "security": [{"BearerAuth": []}],
        "paths": paths,
        "components": COMPONENTS,
    }
