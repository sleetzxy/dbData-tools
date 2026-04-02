import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest


def _make_mock_adapter(rows_per_table=3, fail_tables=None):
    """构造一个 mock adapter，export_csv 写 CSV，import_csv 读 CSV"""
    import csv as csv_mod

    fail_tables = fail_tables or []

    class MockAdapter:
        db_type = "mock"

        def export_csv(self, client, db_config, tables, export_dir,
                       schema="", include_header=True, logger=None):
            result = {"success": True, "exported_tables": [], "error_tables": [], "total_rows": 0}
            for table in tables:
                if table in fail_tables:
                    result["error_tables"].append({"name": table, "error": "mock export error"})
                    result["success"] = False
                    continue
                filepath = os.path.join(export_dir, f"{table}.csv")
                with open(filepath, "w", newline="", encoding="utf-8") as f:
                    writer = csv_mod.writer(f)
                    writer.writerow(["id", "val"])
                    for i in range(rows_per_table):
                        writer.writerow([i, f"v{i}"])
                result["exported_tables"].append({"name": table, "rows": rows_per_table})
                result["total_rows"] += rows_per_table
            return result

        def import_csv(self, client, db_config, table_names, data_dir,
                       schema="", pre_sql_file="", need_backup=False,
                       truncate_before=True, logger=None):
            result = {"success": True, "imported_tables": [], "error_tables": []}
            for table in table_names:
                if table in fail_tables:
                    result["error_tables"].append({"table": table, "error": "mock import error"})
                    result["success"] = False
                    continue
                result["imported_tables"].append(table)
            return result

        def create_client(self, db_config): return object()
        def close_client(self, client): pass

    return MockAdapter()


def test_migrate_tables_success():
    from core.migrator import migrate_tables
    adapter = _make_mock_adapter(rows_per_table=5)
    src_config = {"db_type": "mock", "database": "src"}
    dst_config = {"db_type": "mock", "database": "dst"}

    result = migrate_tables(
        src_config=src_config,
        dst_config=dst_config,
        table_names=["users", "orders"],
        truncate_before=True,
        src_adapter=adapter,
        dst_adapter=adapter,
    )

    assert result["success"] is True
    assert len(result["migrated_tables"]) == 2
    assert result["total_rows"] == 10
    assert result["error_tables"] == []


def test_migrate_tables_empty_list():
    from core.migrator import migrate_tables
    adapter = _make_mock_adapter()
    result = migrate_tables(
        src_config={"db_type": "mock", "database": "src"},
        dst_config={"db_type": "mock", "database": "dst"},
        table_names=[],
        truncate_before=True,
        src_adapter=adapter,
        dst_adapter=adapter,
    )
    assert result["success"] is False
    assert "error" in result


def test_migrate_tables_partial_failure():
    from core.migrator import migrate_tables
    adapter = _make_mock_adapter(fail_tables=["bad_table"])
    result = migrate_tables(
        src_config={"db_type": "mock", "database": "src"},
        dst_config={"db_type": "mock", "database": "dst"},
        table_names=["good_table", "bad_table"],
        truncate_before=True,
        src_adapter=adapter,
        dst_adapter=adapter,
    )
    assert result["success"] is False
    assert len(result["migrated_tables"]) == 1
    assert len(result["error_tables"]) == 1
    assert result["error_tables"][0]["name"] == "bad_table"


def test_migrate_tables_truncate_before_false_passes_param():
    """验证 truncate_before=False 被正确透传到 dst_adapter.import_csv"""
    truncate_calls = []

    import csv as csv_mod

    class TrackingAdapter:
        db_type = "mock"

        def export_csv(self, client, db_config, tables, export_dir,
                       schema="", include_header=True, logger=None):
            for table in tables:
                with open(os.path.join(export_dir, f"{table}.csv"), "w", encoding="utf-8") as f:
                    f.write("id\n1\n")
            return {"success": True, "exported_tables": [{"name": t, "rows": 1} for t in tables],
                    "error_tables": [], "total_rows": len(tables)}

        def import_csv(self, client, db_config, table_names, data_dir,
                       schema="", pre_sql_file="", need_backup=False,
                       truncate_before=True, logger=None):
            truncate_calls.append(truncate_before)
            return {"success": True, "imported_tables": list(table_names), "error_tables": []}

        def create_client(self, db_config): return object()
        def close_client(self, client): pass

    ta = TrackingAdapter()
    from core.migrator import migrate_tables
    migrate_tables(
        src_config={"db_type": "mock", "database": "src"},
        dst_config={"db_type": "mock", "database": "dst"},
        table_names=["t1"],
        truncate_before=False,
        src_adapter=ta,
        dst_adapter=ta,
    )
    assert truncate_calls == [False]
