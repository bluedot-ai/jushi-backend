AUDIT_PATHS = {
    "/api/audits/list": {
        "post": {
            "tags": ["Audits"],
            "summary": "操作审计列表",
            "requestBody": {"$ref": "#/components/requestBodies/AuditListBody"},
            "responses": {"200": {"description": "审计列表"}},
        }
    },
    "/api/audits/export": {
        "post": {
            "tags": ["Audits"],
            "summary": "导出操作审计",
            "requestBody": {"$ref": "#/components/requestBodies/AuditExportBody"},
            "responses": {"200": {"description": "JSON or Excel file download"}},
        }
    },
    "/api/audits/call-statistics": {
        "get": {
            "tags": ["Audits"],
            "summary": "统计六类部署接口调用次数",
            "parameters": [
                {
                    "name": "time_range",
                    "in": "query",
                    "required": False,
                    "description": "统计时间范围，默认 1h",
                    "schema": {
                        "type": "string",
                        "enum": ["1h", "1d", "7d", "30d", "all"],
                        "default": "1h",
                    },
                }
            ],
            "responses": {
                "200": {
                    "description": "接口调用次数、成功数和失败数",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "is_success": {"type": "boolean", "example": True},
                                    "time_range": {"type": "string", "example": "7d"},
                                    "start_at": {
                                        "type": "string",
                                        "nullable": True,
                                        "example": "2026-07-16 15:00:00",
                                    },
                                    "end_at": {
                                        "type": "string",
                                        "example": "2026-07-23 15:00:00",
                                    },
                                    "total_calls": {"type": "integer", "example": 38},
                                    "success_count": {"type": "integer", "example": 35},
                                    "failure_count": {"type": "integer", "example": 3},
                                    "items": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "operation_type": {
                                                    "type": "string",
                                                    "example": "create",
                                                },
                                                "method": {"type": "string", "example": "POST"},
                                                "path": {
                                                    "type": "string",
                                                    "example": "/api/deploy/create-default",
                                                },
                                                "total_calls": {
                                                    "type": "integer",
                                                    "example": 5,
                                                },
                                                "success_count": {
                                                    "type": "integer",
                                                    "example": 4,
                                                },
                                                "failure_count": {
                                                    "type": "integer",
                                                    "example": 1,
                                                },
                                            },
                                        },
                                    },
                                },
                            }
                        }
                    },
                },
                "400": {"description": "time_range 非法"},
            },
        }
    },
}

