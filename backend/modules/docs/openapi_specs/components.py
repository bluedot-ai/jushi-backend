COMPONENTS = {
    "securitySchemes": {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "Token",
            "description": "登录成功后复制 token 到 Authorize，不需要手动添加 Bearer 前缀",
        }
    },
    "parameters": {
        "ItemId": {
            "name": "item_id",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
            "example": "1",
        },
        "UserKeyword": {
            "name": "keyword",
            "in": "query",
            "required": False,
            "schema": {"type": "string"},
            "example": "",
            "description": "按用户名或真实姓名模糊搜索",
        },
        "UserRole": {
            "name": "role",
            "in": "query",
            "required": False,
            "schema": {"type": "string", "enum": ["admin", "operator", "user"]},
            "example": "admin",
            "description": "用户角色筛选",
        },
        "UserStatus": {
            "name": "status",
            "in": "query",
            "required": False,
            "schema": {"type": "string", "enum": ["active", "disabled"]},
            "example": "active",
            "description": "用户状态筛选；不传时返回全部状态",
        },
        "Page": {
            "name": "page",
            "in": "query",
            "required": False,
            "schema": {"type": "integer", "default": 1, "minimum": 1},
            "example": 1,
            "description": "页码",
        },
        "PageSize": {
            "name": "page_size",
            "in": "query",
            "required": False,
            "schema": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            "example": 20,
            "description": "每页数量，最大 100",
        },
        "Namespace": {
            "name": "namespace",
            "in": "query",
            "required": False,
            "schema": {"type": "string"},
            "example": "algorithm",
        },
        "DeploymentName": {
            "name": "deployment_name",
            "in": "query",
            "required": False,
            "schema": {"type": "string"},
            "example": "nvidia-cuda-xxxxxx",
        },
        "PodName": {
            "name": "pod_name",
            "in": "query",
            "required": True,
            "schema": {"type": "string"},
            "example": "nvidia-cuda-xxxxxx-abcde",
        },
        "PodPhase": {
            "name": "phase",
            "in": "query",
            "required": False,
            "schema": {"type": "string"},
            "example": "Running",
        },
        "NodeName": {
            "name": "node_name",
            "in": "query",
            "required": False,
            "schema": {"type": "string"},
            "example": "node-1",
        },
        "TailLines": {
            "name": "tail_lines",
            "in": "query",
            "required": False,
            "schema": {"type": "integer", "default": 200, "minimum": 1},
            "example": 200,
        },
    },
    "requestBodies": {
        "LoginBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/LoginRequest"}
                }
            },
        },
        "DeployEnvelope": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/DeployEnvelope"},
                    "examples": {
                        "nvidia": {
                            "summary": "NVIDIA 资源预检/创建",
                            "value": {
                                "msg_id": "check-001",
                                "serial": "serial-001",
                                "context": "check deploy available",
                                "content": {
                                    "devices": {"NVIDIA/GPU": 1},
                                    "deployType": "NvidiaInfer",
                                    "creator": "admin",
                                    "instance_name": "qwen2.5-72b-prod",
                                },
                            },
                        },
                        "huawei": {
                            "summary": "Huawei Ascend 资源预检/创建",
                            "value": {
                                "msg_id": "check-huawei-001",
                                "serial": "serial-001",
                                "context": "check deploy available",
                                "gpu_resource_name": "huawei.com/Ascend310P",
                                "content": {
                                    "devices": {"Huawei/Ascend310P": 1},
                                    "deployType": "HuaweiInfer",
                                    "creator": "admin",
                                    "instance_name": "ascend-test",
                                },
                            },
                        },
                    },
                }
            },
        },
        "DeployCheckEnvelope": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/DeployEnvelope"},
                    "examples": {
                        "nvidia": {
                            "summary": "NVIDIA 资源预检",
                            "value": {
                                "msg_id": "check-001",
                                "serial": "check-serial-001",
                                "context": "check deploy available",
                                "content": {
                                    "devices": {"NVIDIA/GPU": 1},
                                    "deployType": "NvidiaInfer",
                                    "creator": "admin",
                                    "instance_name": "qwen2.5-72b-prod",
                                },
                            },
                        },
                        "huawei": {
                            "summary": "Huawei Ascend 资源预检",
                            "value": {
                                "msg_id": "check-huawei-001",
                                "serial": "check-serial-001",
                                "context": "check deploy available",
                                "gpu_resource_name": "huawei.com/Ascend310P",
                                "content": {
                                    "devices": {"Huawei/Ascend310P": 1},
                                    "deployType": "HuaweiInfer",
                                    "creator": "admin",
                                    "instance_name": "ascend-test",
                                },
                            },
                        },
                    },
                }
            },
        },
        "DeployCreateEnvelope": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/DeployEnvelope"},
                    "examples": {
                        "nvidia": {
                            "summary": "NVIDIA 创建推理部署",
                            "value": {
                                "msg_id": "create-001",
                                "serial": "create-serial-001",
                                "context": "create inference instance",
                                "content": {
                                    "devices": {"NVIDIA/GPU": 1},
                                    "deployType": "NvidiaInfer",
                                    "creator": "admin",
                                    "instance_name": "qwen2.5-72b-prod",
                                },
                            },
                        },
                        "huawei": {
                            "summary": "Huawei Ascend 创建请求（当前集群暂不支持）",
                            "value": {
                                "msg_id": "create-huawei-001",
                                "serial": "create-serial-001",
                                "context": "create inference instance",
                                "gpu_resource_name": "huawei.com/Ascend310P",
                                "content": {
                                    "devices": {"Huawei/Ascend310P": 1},
                                    "deployType": "HuaweiInfer",
                                    "creator": "admin",
                                    "instance_name": "ascend-test",
                                },
                            },
                        },
                    },
                }
            },
        },
        "NameEnvelope": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/NameEnvelope"},
                    "example": {
                        "msg_id": "retrieve-001",
                        "serial": "retrieve-serial-001",
                        "context": "retrieve deploy",
                        "content": {"name": "nvidia-cuda-xxxxxx"},
                    },
                }
            },
        },
        "DeployReleaseEnvelope": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/NameEnvelope"},
                    "example": {
                        "msg_id": "release-001",
                        "serial": "release-serial-001",
                        "context": "release deploy",
                        "content": {"name": "nvidia-cuda-xxxxxx"},
                    },
                }
            },
        },
        "DeployResetEnvelope": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/NameEnvelope"},
                    "example": {
                        "msg_id": "reset-001",
                        "serial": "reset-serial-001",
                        "context": "restart deploy",
                        "content": {"name": "nvidia-cuda-xxxxxx"},
                    },
                }
            },
        },
        "DeployStopEnvelope": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/NameEnvelope"},
                    "example": {
                        "msg_id": "stop-001",
                        "serial": "stop-serial-001",
                        "context": "stop deploy",
                        "content": {"name": "nvidia-cuda-xxxxxx"},
                    },
                }
            },
        },
        "DeployLogsEnvelope": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/NameEnvelope"},
                    "example": {
                        "msg_id": "logs-001",
                        "serial": "logs-serial-001",
                        "context": "deploy logs",
                        "content": {"name": "nvidia-cuda-xxxxxx"},
                    },
                }
            },
        },
        "DeployListEnvelope": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ClusterEnvelope"},
                    "example": {
                        "msg_id": "list-001",
                        "serial": "list-serial-001",
                        "context": "list deploy",
                        "content": {},
                    },
                }
            },
        },
        "ClusterEnvelope": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ClusterEnvelope"},
                    "example": {
                        "msg_id": "cluster-001",
                        "serial": "serial-001",
                        "context": "query cluster",
                        "content": {},
                    },
                }
            },
        },
        "PortBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/PortRule"},
                    "example": {
                        "port": 50055,
                        "remark": "reserved port",
                    },
                }
            },
        },
        "UserCreateBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/UserCreateRequest"},
                    "example": {
                        "username": "demo_operator",
                        "password": "Init@123",
                        "real_name": "演示运维用户",
                        "role": "operator",
                        "status": "active",
                    },
                }
            },
        },
        "UserUpdateBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/UserUpdateRequest"},
                    "example": {
                        "id": 1,
                        "real_name": "系统管理员",
                        "role": "admin",
                        "status": "active",
                    },
                }
            },
        },
        "UserIdBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/UserIdRequest"},
                    "example": {"id": 2},
                }
            },
        },
        "UserResetPasswordBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/UserResetPasswordRequest"},
                    "example": {
                        "id": 1,
                        "password": "bluedot@123",
                    },
                }
            },
        },
        "AlertListBody": {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AlertListRequest"},
                    "example": {},
                }
            },
        },
        "AlertHistoryBody": {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AlertHistoryRequest"},
                    "example": {
                        "msg_id": "alerts-history-001",
                        "serial": "serial-001",
                        "context": "list alert history",
                        "content": {
                            "status": "resolved",
                            "page": 1,
                            "page_size": 20,
                        },
                    },
                }
            },
        },
        "AlertCreateBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AlertCreateRequest"},
                    "example": {
                        "alert_type": "resource_insufficient",
                        "alert_level": "high",
                        "title": "GPU 资源不足",
                        "message": "当前 GPU 可用数量不足",
                        "source": "deploy",
                        "target_name": "NVIDIA/GPU",
                    },
                }
            },
        },
        "AlertActionBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AlertActionRequest"},
                    "example": {"id": "alert-001", "resolver": "admin"},
                }
            },
        },
        "PodActionBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/PodActionRequest"},
                    "example": {
                        "namespace": "algorithm",
                        "pod_name": "nvidia-cuda-xxxxxx-abcde",
                    },
                }
            },
        },
        "AuditListBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AuditListEnvelope"},
                    "example": {
                        "msg_id": "audit-list-001",
                        "serial": "serial-001",
                        "context": "query audit logs",
                        "content": {
                            "operator": "admin",
                            "operation_type": "create",
                            "keyword": "nvidia",
                            "operation_result": "success",
                            "time_range": "7d",
                            "page": 1,
                            "page_size": 100,
                        },
                    },
                }
            },
        },
        "AuditExportBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AuditExportEnvelope"},
                    "example": {
                        "msg_id": "audit-export-001",
                        "serial": "serial-001",
                        "context": "export audits",
                        "content": {
                            "operator": "admin",
                            "operation_type": "create",
                            "keyword": "nvidia",
                            "operation_result": "success",
                            "time_range": "7d",
                            "format": "excel",
                        },
                    },
                }
            },
        },
    },
    "schemas": {
        "LoginRequest": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "example": "admin"},
                "password": {"type": "string", "example": "bluedot@123"},
            },
            "required": ["username", "password"],
        },
        "DeployEnvelope": {
            "type": "object",
            "properties": {
                "msg_id": {"type": "string", "example": "create-001"},
                "serial": {"type": "string", "example": "serial-001"},
                "context": {"type": "string", "example": "create inference instance"},
                "gpu_resource_name": {
                    "type": "string",
                    "description": "仅 Huawei 场景填写，如 huawei.com/Ascend310P；NVIDIA 场景不要填写",
                },
                "content": {"$ref": "#/components/schemas/DeployContent"},
            },
            "required": ["msg_id", "serial", "context", "content"],
        },
        "DeployContent": {
            "type": "object",
            "properties": {
                "devices": {
                    "type": "object",
                    "additionalProperties": {"type": "integer"},
                    "example": {"NVIDIA/GPU": 1},
                },
                "deployType": {
                    "type": "string",
                    "enum": ["NvidiaInfer", "HuaweiInfer"],
                    "example": "NvidiaInfer",
                },
                "creator": {"type": "string", "example": "alice"},
                "instance_name": {
                    "type": "string",
                    "example": "qwen2.5-72b-prod",
                    "description": "实例展示名称，用户给工作负载起的别名；不传时后端可退回使用 deployment_name",
                },
            },
            "required": ["devices", "deployType", "creator"],
        },
        "NameEnvelope": {
            "type": "object",
            "properties": {
                "msg_id": {"type": "string", "example": "retrieve-001"},
                "serial": {"type": "string", "example": "retrieve-serial-001"},
                "context": {"type": "string", "example": "retrieve deploy"},
                "content": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "example": "nvidia-cuda-xxxxxx"}
                    },
                    "required": ["name"],
                },
            },
            "required": ["msg_id", "serial", "context", "content"],
        },
        "ClusterEnvelope": {
            "type": "object",
            "properties": {
                "msg_id": {"type": "string", "example": "cluster-001"},
                "serial": {"type": "string", "example": "serial-001"},
                "context": {"type": "string", "example": "query cluster"},
                "content": {"type": "object", "example": {}},
            },
            "required": ["msg_id", "serial", "context", "content"],
        },
        "PortRule": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "example": 50055},
                "remark": {"type": "string", "example": "reserved port"},
            },
            "required": ["port"],
        },
        "UserCreateRequest": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "example": "alice"},
                "password": {"type": "string", "example": "Init@123"},
                "real_name": {"type": "string", "example": "Alice"},
                "role": {
                    "type": "string",
                    "enum": ["admin", "operator", "user"],
                    "example": "operator",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "disabled"],
                    "example": "active",
                },
            },
            "required": ["username", "password"],
        },
        "UserUpdateRequest": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "example": 2},
                "real_name": {"type": "string", "example": "Alice Zhang"},
                "role": {
                    "type": "string",
                    "enum": ["admin", "operator", "user"],
                    "example": "operator",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "disabled"],
                    "example": "active",
                },
            },
            "required": ["id"],
        },
        "UserIdRequest": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "example": 2},
            },
            "required": ["id"],
        },
        "UserResetPasswordRequest": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "example": 2},
                "password": {"type": "string", "example": "New@123"},
            },
            "required": ["id", "password"],
        },
        "AlertListRequest": {
            "type": "object",
            "description": "Request body is optional. Empty body or {} means cluster-wide open alerts, page=1, page_size=20.",
            "properties": {
                "msg_id": {"type": "string", "example": "alerts-list-001"},
                "serial": {"type": "string", "example": "serial-001"},
                "context": {"type": "string", "example": "list cluster alerts"},
                "content": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "enum": ["cluster", "namespace"], "example": "cluster"},
                        "cluster_name": {"type": "string", "example": "kpanda-global-cluster"},
                        "namespace": {"type": "string", "example": "all"},
                        "level": {"type": "string", "enum": ["all", "high", "medium", "low"], "example": "all"},
                        "status": {"type": "string", "enum": ["open", "resolved", "ignored"], "example": "open"},
                        "deployment_name": {"type": "string", "example": "nvidia-cuda-xxxxxx"},
                        "page": {"type": "integer", "example": 1},
                        "page_size": {"type": "integer", "example": 20},
                    },
                },
            },
        },
        "AlertHistoryRequest": {
            "type": "object",
            "description": "Request body is optional. Empty body or {} means resolved and ignored alert history, page=1, page_size=20. This endpoint does not scan Kubernetes.",
            "properties": {
                "msg_id": {"type": "string", "example": "alerts-history-001"},
                "serial": {"type": "string", "example": "serial-001"},
                "context": {"type": "string", "example": "list alert history"},
                "content": {
                    "type": "object",
                    "properties": {
                        "cluster_name": {"type": "string", "example": "kpanda-global-cluster"},
                        "namespace": {"type": "string", "example": "all"},
                        "level": {"type": "string", "enum": ["all", "high", "medium", "low"], "example": "all"},
                        "status": {"type": "string", "enum": ["resolved", "ignored"], "example": "resolved"},
                        "deployment_name": {"type": "string", "example": "nvidia-cuda-xxxxxx"},
                        "page": {"type": "integer", "example": 1},
                        "page_size": {"type": "integer", "example": 20},
                    },
                },
            },
        },
        "AlertCreateRequest": {
            "type": "object",
            "properties": {
                "alert_type": {"type": "string", "example": "resource_insufficient"},
                "alert_level": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "example": "high",
                },
                "title": {"type": "string", "example": "GPU 资源不足"},
                "message": {"type": "string", "example": "当前 GPU 可用数量不足"},
                "source": {"type": "string", "example": "deploy"},
                "target_name": {"type": "string", "example": "NVIDIA/GPU"},
                "cluster_name": {"type": "string", "example": "kpanda-global-cluster"},
                "namespace": {"type": "string", "example": "algorithm"},
            },
        },
        "AlertActionRequest": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "example": "alert-001"},
                "resolver": {"type": "string", "example": "admin"},
            },
            "required": ["id"],
        },
        "PodActionRequest": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "example": "algorithm"},
                "pod_name": {"type": "string", "example": "nvidia-cuda-xxxxxx-abcde"},
            },
            "required": ["namespace", "pod_name"],
        },
        "AuditContent": {
            "type": "object",
            "properties": {
                "operator": {"type": "string", "example": "admin"},
                "operation_type": {"type": "string", "example": "create"},
                "keyword": {"type": "string", "example": "nvidia"},
                "operation_result": {
                    "type": "string",
                    "enum": ["success", "failure"],
                    "example": "success",
                },
                "time_range": {
                    "type": "string",
                    "enum": ["1h", "1d", "7d", "30d", "all"],
                    "example": "7d",
                },
                "format": {"type": "string", "enum": ["json", "excel"], "example": "excel"},
                "page": {"type": "integer", "example": 1},
                "page_size": {"type": "integer", "example": 100},
            },
        },
        "AuditListEnvelope": {
            "type": "object",
            "properties": {
                "msg_id": {"type": "string", "example": "audit-list-001"},
                "serial": {"type": "string", "example": "serial-001"},
                "context": {"type": "string", "example": "query audit logs"},
                "content": {"$ref": "#/components/schemas/AuditContent"},
            },
            "required": ["msg_id", "serial", "context"],
        },
        "LogoStatus": {
            "type": "object",
            "properties": {
                "logo_url": {
                    "type": "string",
                    "example": "/api/system/logo/file",
                    "description": "Logo 图片 URL，空字符串表示未启用",
                },
                "logo_enabled": {
                    "type": "boolean",
                    "example": True,
                    "description": "自定义 Logo 是否启用",
                },
            },
        },
        "LogoUploadResult": {
            "type": "object",
            "properties": {
                "is_success": {"type": "boolean", "example": True},
                "logo_url": {"type": "string", "example": "/api/system/logo/file"},
                "logo_enabled": {"type": "boolean", "example": True},
            },
        },
        "AuditExportEnvelope": {
            "type": "object",
            "properties": {
                "msg_id": {"type": "string", "example": "audit-export-001"},
                "serial": {"type": "string", "example": "serial-001"},
                "context": {"type": "string", "example": "export audits"},
                "content": {"$ref": "#/components/schemas/AuditContent"},
            },
            "required": ["msg_id", "serial", "context"],
        },
    },
}

