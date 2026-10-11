RESOURCE_PATHS = {
    "/api/resources/summary": {
        "get": {
            "tags": ["Resources"],
            "summary": "资源概览",
            "description": "查询集群资源总览，用于首页和资源中心顶部统计卡片。",
            "responses": {"200": {"description": "资源概览"}},
        }
    },
    "/api/resources/nodes": {
        "get": {
            "tags": ["Resources"],
            "summary": "节点资源列表",
            "description": "查询节点维度的 GPU / vGPU / 显存 / 算力 / CPU / 内存资源状态。",
            "responses": {"200": {"description": "节点列表"}},
        }
    },
    "/api/resources/nodes/{node_name}/gpus": {
        "get": {
            "tags": ["Resources"],
            "summary": "节点物理加速卡实时明细",
            "description": "查询 Ready、可调度节点上的真实 NVIDIA GPU 或 Ascend NPU 单卡利用率与显存明细。卡数根据 Prometheus 稳定设备标识动态生成，不包含 vGPU。",
            "parameters": [
                {
                    "name": "node_name",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": {"description": "节点单卡实时明细或可读业务错误"},
                "401": {"description": "未登录"},
            },
        }
    },
    "/api/resources/nodes/{node_name}/gpu-trend": {
        "get": {
            "tags": ["Resources"],
            "summary": "节点物理加速卡趋势",
            "description": "按真实物理卡返回显存利用率历史序列。数据由 jushi-api 每分钟从 Prometheus 采集并保存到 MySQL，1h、24h、7d 分别按 1 分钟、15 分钟、1 小时分桶；空桶返回 null，不补 0。",
            "parameters": [
                {
                    "name": "node_name",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
                {
                    "name": "metric",
                    "in": "query",
                    "required": False,
                    "schema": {
                        "type": "string",
                        "enum": ["memory_utilization"],
                        "default": "memory_utilization",
                    },
                },
                {
                    "name": "range",
                    "in": "query",
                    "required": False,
                    "schema": {
                        "type": "string",
                        "enum": ["1h", "24h", "7d"],
                        "default": "1h",
                    },
                },
            ],
            "responses": {
                "200": {"description": "节点单卡趋势或可读业务错误"},
                "401": {"description": "未登录"},
            },
        }
    },
    "/api/resources/gpus": {
        "get": {
            "tags": ["Resources"],
            "summary": "GPU / vGPU 资源统计",
            "description": "按资源类型统计总量、已用量和可用量；category_items 按 Prometheus 逐卡型号聚合，混合型号节点不套用节点标签，未识别型号返回 Unknown。diagnostics.card_inventory 给出监控查询和识别完整性诊断。",
            "responses": {"200": {"description": "GPU 统计"}},
        }
    },
    "/api/resources/quotas": {
        "get": {
            "tags": ["Resources"],
            "summary": "配额列表",
            "description": "查询命名空间 ResourceQuota 信息；无权限时降级为空列表，不阻塞页面。",
            "responses": {"200": {"description": "配额列表"}},
        }
    },
    "/api/resources/cards": {
        "get": {
            "tags": ["Resources"],
            "summary": "资源卡片列表",
            "description": "查询显卡列表。逐卡 card_id、vendor、device_index（exporter 原始零基序号）、device_name、gpu_model 来自 Prometheus 设备标签。监控缺失保留未识别占位，is_real_physical_card=false，不套用节点型号。已识别不表示已分配，无法绑定具体 UUID 的分配状态和已用显存返回 null，节点推导容量仍保留估算标记。新增 model_source 和 diagnostics.card_inventory；接口鉴权及原字段结构保持兼容。",
            "responses": {"200": {"description": "资源卡片列表"}},
        }
    },
    "/api/resources/trend": {
        "get": {
            "tags": ["Resources"],
            "summary": "资源趋势",
            "description": "查询完整时间范围的资源趋势。1h 实时查询；24h 和 7d 使用后端内存缓存，分别每 15 分钟和 1 小时整份覆盖刷新。缓存未就绪时返回 cache_status=warming，客户端可按 retry_after_seconds 重试。",
            "parameters": [
                {
                    "name": "range",
                    "in": "query",
                    "required": False,
                    "description": "趋势范围：1h 每分钟一桶（60 点）；24h 每 15 分钟一桶（96 点）；7d 每小时一桶（168 点）。",
                    "schema": {
                        "type": "string",
                        "enum": ["1h", "24h", "7d"],
                        "default": "1h",
                    },
                }
            ],
            "responses": {"200": {"description": "资源趋势"}},
        }
    },
    "/api/resources/recommendation": {
        "get": {
            "tags": ["Resources"],
            "summary": "资源推荐策略",
            "description": "根据当前 GPU / vGPU / 显存 / 算力资源余量返回推荐策略。",
            "responses": {"200": {"description": "资源推荐策略"}},
        }
    },
}
