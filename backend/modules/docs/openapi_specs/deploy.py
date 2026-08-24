DEPLOY_PATHS = {
    "/api/deploy/check-available": {
        "post": {
            "tags": ["Deploy"],
            "summary": "资源预检",
            "requestBody": {"$ref": "#/components/requestBodies/DeployCheckEnvelope"},
            "responses": {"200": {"description": "资源可创建"}},
        }
    },
    "/api/deploy/create-default": {
        "post": {
            "tags": ["Deploy"],
            "summary": "创建推理部署",
            "description": "当前创建链路仅支持 NVIDIA；Huawei/Ascend310P 创建请求会返回暂不支持。",
            "requestBody": {"$ref": "#/components/requestBodies/DeployCreateEnvelope"},
            "responses": {"200": {"description": "创建成功"}},
        }
    },
    "/api/deploy/retrieve": {
        "post": {
            "tags": ["Deploy"],
            "summary": "查询单个部署",
            "requestBody": {"$ref": "#/components/requestBodies/NameEnvelope"},
            "responses": {"200": {"description": "部署详情"}},
        }
    },
    "/api/deploy/release": {
        "post": {
            "tags": ["Deploy"],
            "summary": "释放部署",
            "requestBody": {"$ref": "#/components/requestBodies/DeployReleaseEnvelope"},
            "responses": {"200": {"description": "释放结果"}},
        }
    },
    "/api/deploy/reset": {
        "post": {
            "tags": ["Deploy"],
            "summary": "重启部署",
            "description": (
                "运行中的 GPU 单副本部署通过删除旧 Pod 触发 Deployment 自动重建，避免 rollout restart 先创建新 Pod 导致 GPU 不足。"
                "已停止部署保持 PaaS 原有语义，reset 不负责恢复启动。"
            ),
            "requestBody": {"$ref": "#/components/requestBodies/DeployResetEnvelope"},
            "responses": {"200": {"description": "重启结果"}},
        }
    },
    "/api/deploy/stop": {
        "post": {
            "tags": ["Deploy"],
            "summary": "停止部署",
            "description": "直接调用 Kubernetes API 将 Deployment replicas 缩为 0，不删除 Deployment 或 Service。",
            "requestBody": {"$ref": "#/components/requestBodies/DeployStopEnvelope"},
            "responses": {"200": {"description": "停止结果"}},
        }
    },
    "/api/deploy/logs": {
        "post": {
            "tags": ["Deploy"],
            "summary": "部署 Pod 描述",
            "description": "按 deployment_name 查询对应 Pod，并以 text/plain 返回接近 kubectl describe pod 的完整描述文本；不会返回容器 stdout 日志。",
            "requestBody": {"$ref": "#/components/requestBodies/DeployLogsEnvelope"},
            "responses": {
                "200": {
                    "description": "部署 Pod 描述",
                    "content": {"text/plain": {"schema": {"type": "string"}}},
                }
            },
        }
    },
    "/api/deploy/list": {
        "post": {
            "tags": ["Deploy"],
            "summary": "部署列表",
            "requestBody": {"$ref": "#/components/requestBodies/DeployListEnvelope"},
            "responses": {"200": {"description": "部署列表"}},
        }
    },
}
