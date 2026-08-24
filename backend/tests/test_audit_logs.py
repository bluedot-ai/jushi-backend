import unittest
from datetime import datetime
from unittest.mock import patch

from flask import Flask

from backend.modules.audits import audits_bp
from backend.modules.audits import routes as audit_routes
from backend.modules.audits.schema import (
    normalize_audit_export,
    normalize_audit_list,
)
from backend.modules.logs import repository
from backend.modules.logs.schema import normalize_log_query


class _FakeCursor:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, list(params or [])))
        return 1

    def fetchone(self):
        return {"total": 2}

    def fetchall(self):
        return [
            {
                "id": 2,
                "operator": "",
                "is_success": 0,
                "created_at": datetime(2026, 7, 23, 12, 0, 0),
            },
            {
                "id": 1,
                "operator": "admin",
                "is_success": 1,
                "created_at": datetime(2026, 7, 23, 11, 0, 0),
            },
        ]


class _FakeConnection:
    def __init__(self):
        self.cursor_instance = _FakeCursor()

    def cursor(self):
        return self.cursor_instance

    def close(self):
        return None


class AuditLogTests(unittest.TestCase):
    def test_log_query_normalizes_pagination_result_and_range(self):
        query = normalize_log_query({
            "page": "2",
            "page_size": "500",
            "operation_result": "失败",
            "time_range": "7d",
        })

        self.assertEqual(query["page"], 2)
        self.assertEqual(query["page_size"], 100)
        self.assertEqual(query["operation_result"], 0)
        self.assertEqual(query["time_range"], "7d")

    def test_invalid_log_query_values_fall_back_instead_of_raising(self):
        query = normalize_log_query({
            "page": "not-a-number",
            "page_size": "",
            "tail_lines": "invalid",
            "time_range": "unsupported",
        })

        self.assertEqual(query["page"], 1)
        self.assertEqual(query["page_size"], 100)
        self.assertEqual(query["tail_lines"], 200)
        self.assertEqual(query["time_range"], "all")

    def test_audit_schemas_keep_export_range_and_result(self):
        payload = {
            "content": {
                "operation_result": "success",
                "time_range": "30d",
                "format": "excel",
                "page": 3,
                "page_size": 20,
            }
        }

        list_query = normalize_audit_list(payload)
        export_query = normalize_audit_export(payload)

        self.assertEqual(list_query["operation_result"], 1)
        self.assertEqual(list_query["time_range"], "30d")
        self.assertEqual(export_query["format"], "excel")
        self.assertEqual(export_query["time_range"], "30d")

    def test_database_list_orders_newest_first_and_normalizes_rows(self):
        connection = _FakeConnection()
        with (
            patch.object(repository, "_db_available", return_value=True),
            patch.object(repository, "get_connection", return_value=connection),
        ):
            result = repository.list_operation_logs({
                "page": 1,
                "page_size": 100,
                "time_range": "all",
            })

        select_sql = connection.cursor_instance.statements[1][0]
        self.assertIn("ORDER BY created_at DESC, id DESC", select_sql)
        self.assertEqual(result["total"], 2)
        self.assertFalse(result["items"][0]["is_success"])
        self.assertEqual(result["items"][0]["operator"], "anonymous")
        self.assertTrue(result["items"][1]["is_success"])
        self.assertFalse(repository._normalize_row({"is_success": "0"})["is_success"])

    def test_filters_include_result_and_time_cutoff(self):
        clauses, params = repository._operation_log_filters({
            "operation_result": 0,
            "time_range": "1h",
        })

        self.assertIn("is_success = %s", clauses)
        self.assertIn("created_at >= %s", clauses)
        self.assertEqual(params[0], 0)
        self.assertIsInstance(params[1], datetime)

    def test_export_filename_contains_date_log_name_and_range(self):
        filename = audit_routes._export_filename("xlsx", "7d")

        self.assertRegex(filename, r"^\d{8}_审计日志_7d\.xlsx$")
        headers = audit_routes._download_headers(filename)
        self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])

    @patch("backend.modules.audits.routes.service.export_audit_logs")
    def test_excel_export_applies_range_to_download_filename(self, export_logs):
        export_logs.return_value = [{
            "id": 1,
            "operation_type": "create",
            "operator": "admin",
            "is_success": True,
            "created_at": "2026-07-23 12:00:00",
        }]
        app = Flask(__name__)
        app.register_blueprint(audits_bp, url_prefix="/api/audits")

        response = app.test_client().post(
            "/api/audits/export",
            json={"content": {"format": "excel", "time_range": "1h"}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.mimetype,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        disposition = response.headers["Content-Disposition"]
        self.assertIn("_1h.xlsx", disposition)
        self.assertIn("%E5%AE%A1%E8%AE%A1%E6%97%A5%E5%BF%97", disposition)


if __name__ == "__main__":
    unittest.main()

