import unittest
from datetime import datetime
from pathlib import Path
import re
from unittest.mock import MagicMock, patch

from backend.modules.resources import gpu_allocation_repository as repo


class GpuAllocationRepositoryTests(unittest.TestCase):
    def connection(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        return conn, cursor

    def test_save_uses_parameters_and_upsert_without_ddl(self):
        conn, cursor = self.connection()
        with patch.object(repo, "get_connection", return_value=conn):
            self.assertIsNone(repo.save_snapshot({"cluster_name": "x'; DROP TABLE x;--", "sampled_at": datetime(2026, 10, 10)}))
        sql, params = cursor.execute.call_args.args
        self.assertNotIn("DROP TABLE", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertEqual(params["sample_interval_seconds"], 300)
        self.assertEqual(params["sample_slot"], datetime(2026, 10, 10))
        self.assertNotIn("CREATE TABLE", sql)
        conn.close.assert_called_once()

    def test_actual_time_preserved_and_period_slot_idempotency_key(self):
        conn, cursor = self.connection()
        at = datetime(2026, 10, 10, 15, 3, 21)
        with patch.object(repo, "get_connection", return_value=conn):
            self.assertIsNone(repo.save_snapshot({"sampled_at": at}))
        sql, row = cursor.execute.call_args.args
        self.assertEqual(row["sampled_at"], at)
        self.assertEqual(row["sample_slot"], datetime(2026, 10, 10, 15))
        self.assertIn("sampled_at = VALUES(sampled_at)", sql)
        self.assertNotIn("sample_slot = VALUES(sample_slot)", sql)

    def test_three_schema_definitions_match_and_have_20_columns(self):
        db = Path(__file__).resolve().parents[1] / "db"
        filename = "20261010_001_create_gpu_allocation_snapshot.sql"
        sql = (db / filename).read_text(encoding="utf-8")
        self.assertEqual(sql, (db / "migrations" / filename).read_text(encoding="utf-8"))
        self.assertIn(sql.strip(), (db / "init.sql").read_text(encoding="utf-8"))
        columns = re.findall(r"^  ([a-z_]+) (?:BIGINT|DATETIME|VARCHAR|INT|DECIMAL|BOOLEAN)", sql, re.M)
        self.assertEqual(len(columns), 20)
        self.assertEqual(set(columns), set(repo.SNAPSHOT_FIELDS) | {"id", "created_at"})
        self.assertIn("UNIQUE KEY uk_gpu_allocation_cluster_vendor_slot (cluster_name, vendor, sample_slot)", sql)
        self.assertIn("KEY idx_gpu_allocation_cluster_vendor_time (cluster_name, vendor, sampled_at)", sql)
        self.assertIn("vendor VARCHAR(16) NOT NULL DEFAULT 'nvidia'", sql)

    def test_neighbors_returned_without_cross_cluster_queries(self):
        conn, cursor = self.connection()
        before, after = {"id": 1}, {"id": 3}
        cursor.fetchone.side_effect = [before, after]
        cursor.fetchall.return_value = [{"id": 2}]
        start, end = datetime(2026, 10, 1), datetime(2026, 10, 2)
        with patch.object(repo, "get_connection", return_value=conn):
            rows, error = repo.load_snapshots("cluster-1", start, end)
        self.assertIsNone(error)
        self.assertEqual([row["id"] for row in rows], [1, 2, 3])
        for call in cursor.execute.call_args_list:
            sql, args = call.args
            self.assertIn("cluster_name = %s", sql)
            self.assertIn("vendor = %s", sql)
            self.assertEqual(args[0], "cluster-1")
            self.assertEqual(args[1], "all")
        conn.close.assert_called_once()

    def test_vendor_scope_parameterized_for_all_neighbors(self):
        conn, cursor = self.connection()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        with patch.object(repo, "get_connection", return_value=conn):
            rows, error = repo.load_snapshots("cluster", datetime(2026, 10, 1), datetime(2026, 10, 2), vendor="ascend")
        self.assertEqual(rows, [])
        self.assertIsNone(error)
        for call in cursor.execute.call_args_list:
            self.assertEqual(call.args[1][1], "ascend")

    def test_vendor_is_part_of_upsert_key_not_mutable(self):
        self.assertIn("%(vendor)s", repo.UPSERT_SQL)
        self.assertNotIn("vendor = VALUES(vendor)", repo.UPSERT_SQL)
        for version, expected in (("physical-gpu-v1", "nvidia"), ("physical-accelerator-v2", "all")):
            conn, cursor = self.connection()
            with patch.object(repo, "get_connection", return_value=conn):
                self.assertIsNone(repo.save_snapshot({"calculation_version": version}))
            self.assertEqual(cursor.execute.call_args.args[1]["vendor"], expected)

    def test_invalid_vendor_never_connects_or_injects_sql(self):
        with patch.object(repo, "get_connection") as connect:
            _, error = repo.load_snapshots("c", datetime(2026, 10, 1), datetime(2026, 10, 2), vendor="all' OR 1=1")
            self.assertIsNotNone(error)
            self.assertIsNotNone(repo.save_snapshot({"vendor": "huawei"}))
            connect.assert_not_called()

    def test_legacy_schema_upgrade_is_additive_guarded_and_keeps_versions(self):
        db = Path(__file__).resolve().parents[1] / "db"
        filename = "20261010_002_add_gpu_allocation_vendor.sql"
        sql = (db / filename).read_text(encoding="utf-8")
        self.assertEqual(sql, (db / "migrations" / filename).read_text(encoding="utf-8"))
        self.assertIn("information_schema.columns", sql)
        self.assertIn("@gpu_allocation_vendor_exists = 0", sql)
        self.assertIn("DEFAULT ''nvidia''", sql)
        self.assertIn("information_schema.statistics", sql)
        self.assertIn("CONCAT_WS(', '", sql)
        self.assertIn("ADD UNIQUE KEY uk_gpu_allocation_cluster_vendor_slot (cluster_name, vendor, sample_slot)", sql)
        self.assertNotRegex(sql, r"(?i)\b(?:DELETE|TRUNCATE|DROP TABLE|UPDATE gpu_allocation_snapshot)\b")
        self.assertNotIn("SET calculation_version", sql)

    def test_cleanup_has_bounded_work(self):
        conn, cursor = self.connection()
        cursor.execute.return_value = 5
        cutoff = datetime(2026, 4, 1)
        with patch.object(repo, "get_connection", return_value=conn):
            deleted, error = repo.cleanup_snapshots(cutoff, batch_size=5, max_batches=2)
        self.assertEqual(deleted, 10)
        self.assertIsNone(error)
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertEqual(cursor.execute.call_args.args[1], (cutoff, 5))
        conn.close.assert_called_once()

    def test_database_failure_is_sanitized_and_connection_closed(self):
        conn, cursor = self.connection()
        cursor.execute.side_effect = RuntimeError("password=secret@customer-host")
        with patch.object(repo, "get_connection", return_value=conn):
            error = repo.save_snapshot({})
        self.assertNotIn("secret", error)
        self.assertNotIn("customer-host", error)
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
