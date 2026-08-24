LOG_PATHS = {
    "/api/logs/operations": {
        "get": {
            "tags": ["Logs"],
            "summary": "操作日志",
            "description": "按创建时间倒序返回操作日志，默认读取最新 100 条。",
            "parameters": [
                {
                    "name": "operator",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "操作人精确筛选",
                },
                {
                    "name": "operation_type",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "操作类型精确筛选",
                },
                {
                    "name": "keyword",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "操作对象或错误信息关键词",
                },
                {
                    "name": "operation_result",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string", "enum": ["success", "failure"]},
                    "description": "操作结果",
                },
                {
                    "name": "time_range",
                    "in": "query",
                    "required": False,
                    "schema": {
                        "type": "string",
                        "enum": ["1h", "1d", "7d", "30d", "all"],
                        "default": "all",
                    },
                    "description": "日志时间范围",
                },
                {"$ref": "#/components/parameters/Page"},
                {
                    "name": "page_size",
                    "in": "query",
                    "required": False,
                    "schema": {
                        "type": "integer",
                        "default": 100,
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "description": "每页数量，最大 100",
                },
            ],
            "responses": {"200": {"description": "操作日志"}},
        }
    },
    "/api/logs/instance": {
        "get": {
            "tags": ["Logs"],
            "summary": "实例日志",
            "parameters": [
                {"$ref": "#/components/parameters/DeploymentName"},
                {"$ref": "#/components/parameters/TailLines"},
            ],
            "responses": {"200": {"description": "实例日志"}},
        }
    },
    "/api/logs/pod": {
        "get": {
            "tags": ["Logs"],
            "summary": "Pod 日志",
            "parameters": [
                {"$ref": "#/components/parameters/Namespace"},
                {"$ref": "#/components/parameters/PodName"},
                {"$ref": "#/components/parameters/TailLines"},
            ],
            "responses": {"200": {"description": "Pod 日志"}},
        }
    },
}

