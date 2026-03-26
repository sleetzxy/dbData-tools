import os
import sys
import tempfile
import shutil
import io
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from core.exporter_csv import export_tables_to_csv
from core.exporter_db import export_database_to_sql
from core.importer_csv import import_csv_to_db
from db.adapters import get_adapter_for_config
from db.adapters.clickhouse_adapter import ClickHouseAdapter
from db.adapters.postgresql_adapter import PostgreSQLAdapter
from db.connection import ConnectionHandle


def _make_export_dir():
    base_dir = os.path.join(os.path.dirname(__file__), ".tmp_exports")
    os.makedirs(base_dir, exist_ok=True)
    return tempfile.mkdtemp(dir=base_dir)


def _make_import_dir():
    base_dir = os.path.join(os.path.dirname(__file__), ".tmp_imports")
    os.makedirs(base_dir, exist_ok=True)
    return tempfile.mkdtemp(dir=base_dir)



def test_postgresql_config_dispatches_to_postgresql_adapter():
    config = {
        "name": "pg",
        "db_type": "postgresql",
        "host": "127.0.0.1",
        "database": "postgres",
        "user": "postgres",
        "password": "",
    }

    adapter = get_adapter_for_config(config)

    assert isinstance(adapter, PostgreSQLAdapter)


def test_clickhouse_config_dispatches_to_clickhouse_adapter():
    config = {
        "name": "ch",
        "db_type": "clickhouse",
        "host": "127.0.0.1",
        "database": "default",
        "user": "default",
        "password": "",
    }

    adapter = get_adapter_for_config(config)

    assert isinstance(adapter, ClickHouseAdapter)


def test_export_tables_to_csv_dispatches_postgresql_adapter(monkeypatch):
    called = {}
    export_dir = _make_export_dir()

    class DummyClient:
        pass

    def fake_create_client(self, db_config):
        return DummyClient()

    def fake_close_client(self, client):
        return None

    def fake_export_csv(
        self,
        client,
        db_config,
        tables,
        export_dir,
        schema="public",
        include_header=True,
        logger=None,
    ):
        called["adapter"] = "postgresql"
        return {
            "success": True,
            "exported_tables": [],
            "error_tables": [],
            "total_rows": 0,
            "schema": schema,
        }

    monkeypatch.setattr(PostgreSQLAdapter, "create_client", fake_create_client)
    monkeypatch.setattr(PostgreSQLAdapter, "close_client", fake_close_client)
    monkeypatch.setattr(PostgreSQLAdapter, "export_csv", fake_export_csv)

    config = {
        "name": "pg",
        "db_type": "postgresql",
        "host": "127.0.0.1",
        "database": "postgres",
        "user": "postgres",
        "password": "",
    }

    try:
        result = export_tables_to_csv(
            db_config=config,
            tables=["demo"],
            export_dir=export_dir,
            schema="public",
            include_header=True,
        )
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)

    assert called["adapter"] == "postgresql"
    assert result["success"] is True


def test_export_tables_to_csv_dispatches_clickhouse_adapter(monkeypatch):
    called = {}
    export_dir = _make_export_dir()

    class DummyClient:
        pass

    def fake_create_client(self, db_config):
        return DummyClient()

    def fake_close_client(self, client):
        return None

    def fake_export_csv(
        self,
        client,
        db_config,
        tables,
        export_dir,
        schema="",
        include_header=True,
        logger=None,
    ):
        called["adapter"] = "clickhouse"
        return {
            "success": True,
            "exported_tables": [],
            "error_tables": [],
            "total_rows": 0,
            "schema": schema,
        }

    monkeypatch.setattr(ClickHouseAdapter, "create_client", fake_create_client)
    monkeypatch.setattr(ClickHouseAdapter, "close_client", fake_close_client)
    monkeypatch.setattr(ClickHouseAdapter, "export_csv", fake_export_csv)

    config = {
        "name": "ch",
        "db_type": "clickhouse",
        "host": "127.0.0.1",
        "database": "default",
        "user": "default",
        "password": "",
    }

    try:
        result = export_tables_to_csv(
            db_config=config,
            tables=["demo"],
            export_dir=export_dir,
            schema="public",
            include_header=False,
        )
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)

    assert called["adapter"] == "clickhouse"
    assert result["success"] is True
    assert result["schema"] == ""



def test_export_database_to_sql_dispatches_postgresql_adapter(monkeypatch):
    called = {}

    class DummyAdapter:
        def export_sql(
            self,
            client,
            db_config,
            export_dir,
            schema,
            exclude_tables,
            include_truncate,
            logger,
        ):
            called["schema"] = schema
            called["adapter"] = "postgresql"
            return {"success": True, "schema": schema}

    handle = ConnectionHandle(
        db_type="postgresql",
        adapter=DummyAdapter(),
        client=object(),
    )

    monkeypatch.setattr("core.exporter_db.create_connection", lambda db_config, logger: handle)
    monkeypatch.setattr("core.exporter_db.close_connection", lambda conn, logger: None)

    result = export_database_to_sql(
        db_config={
            "name": "pg",
            "db_type": "postgresql",
            "host": "127.0.0.1",
            "database": "postgres",
            "user": "postgres",
            "password": "",
        },
        export_dir=".",
        schema="public",
        exclude_tables=["skip"],
        include_truncate=False,
    )

    assert called["adapter"] == "postgresql"
    assert called["schema"] == "public"
    assert result["success"] is True
    assert result["schema"] == "public"


def test_export_database_to_sql_dispatches_clickhouse_adapter_schema_empty(monkeypatch):
    called = {}

    class DummyAdapter:
        def export_sql(
            self,
            client,
            db_config,
            export_dir,
            schema,
            exclude_tables,
            include_truncate,
            logger,
        ):
            called["schema"] = schema
            called["adapter"] = "clickhouse"
            return {"success": True, "schema": schema}

    handle = ConnectionHandle(
        db_type="clickhouse",
        adapter=DummyAdapter(),
        client=object(),
    )

    monkeypatch.setattr("core.exporter_db.create_connection", lambda db_config, logger: handle)
    monkeypatch.setattr("core.exporter_db.close_connection", lambda conn, logger: None)

    result = export_database_to_sql(
        db_config={
            "name": "ch",
            "db_type": "clickhouse",
            "host": "127.0.0.1",
            "database": "default",
            "user": "default",
            "password": "",
        },
        export_dir=".",
        schema="public",
        exclude_tables=["skip"],
        include_truncate=True,
    )

    assert called["adapter"] == "clickhouse"
    assert called["schema"] == ""
    assert result["success"] is True
    assert result["schema"] == ""

def test_export_tables_to_csv_clickhouse_failure_schema_is_empty(monkeypatch):
    def fake_create_connection(db_config, logger):
        return None

    monkeypatch.setattr("core.exporter_csv.create_connection", fake_create_connection)

    config = {
        "name": "ch",
        "db_type": "clickhouse",
        "host": "127.0.0.1",
        "database": "default",
        "user": "default",
        "password": "",
    }

    result = export_tables_to_csv(
        db_config=config,
        tables=["demo"],
        export_dir=".",
        schema="public",
        include_header=False,
    )

    assert result["success"] is False
    assert result["schema"] == ""


def test_export_tables_to_csv_clickhouse_exception_schema_is_empty(monkeypatch):
    class DummyAdapter:
        def export_csv(self, *args, **kwargs):
            raise RuntimeError("boom")

    handle = ConnectionHandle(
        db_type="clickhouse",
        adapter=DummyAdapter(),
        client=object(),
    )

    monkeypatch.setattr("core.exporter_csv.create_connection", lambda db_config, logger: handle)
    monkeypatch.setattr("core.exporter_csv.close_connection", lambda conn, logger: None)

    config = {
        "name": "ch",
        "db_type": "clickhouse",
        "host": "127.0.0.1",
        "database": "default",
        "user": "default",
        "password": "",
    }

    result = export_tables_to_csv(
        db_config=config,
        tables=["demo"],
        export_dir=".",
        schema="public",
        include_header=False,
    )

    assert result["success"] is False
    assert result["schema"] == ""
    assert "boom" in result["error"]


def test_gui_csv_exporter_module_imports():
    __import__("gui.pages.csv.exporter")


def test_export_tables_to_csv_clickhouse_outer_exception_schema_is_empty(monkeypatch):
    def boom(db_config, logger):
        raise RuntimeError("boom")

    monkeypatch.setattr("core.exporter_csv.create_connection", boom)

    config = {
        "name": "ch",
        "db_type": "clickhouse",
        "host": "127.0.0.1",
        "database": "default",
        "user": "default",
        "password": "",
    }

    result = export_tables_to_csv(
        db_config=config,
        tables=["demo"],
        export_dir=".",
        schema="public",
        include_header=False,
    )

    assert result["success"] is False
    assert result["schema"] == ""
    assert "boom" in result["error"]

def test_import_csv_dispatches_postgresql_adapter(monkeypatch):
    called = {}
    import_dir = _make_import_dir()

    class DummyAdapter:
        def import_csv(
            self,
            client,
            db_config,
            table_names,
            data_dir,
            schema,
            pre_sql_file,
            need_backup,
            logger,
        ):
            called["adapter"] = "postgresql"
            called["schema"] = schema
            return {
                "success": True,
                "imported_tables": table_names,
                "error_tables": [],
                "backup_path": None,
                "data_directory": data_dir,
                "schema": schema,
            }

    handle = ConnectionHandle(
        db_type="postgresql",
        adapter=DummyAdapter(),
        client=object(),
    )

    monkeypatch.setattr("core.importer_csv.create_connection", lambda db_config, logger: handle)
    monkeypatch.setattr("core.importer_csv.close_connection", lambda conn, logger: None)
    monkeypatch.setattr("core.importer_csv.get_data_directory", lambda *args, **kwargs: import_dir)
    monkeypatch.setattr("core.importer_csv.get_table_names_from_csv", lambda data_dir: ["demo"])

    try:
        result = import_csv_to_db(
            db_config={
                "name": "pg",
                "db_type": "postgresql",
                "host": "127.0.0.1",
                "database": "postgres",
                "user": "postgres",
                "password": "",
            },
            data_source=import_dir,
            source_type="folder",
            schema="public",
        )
    finally:
        import shutil
        shutil.rmtree(import_dir, ignore_errors=True)

    assert called["adapter"] == "postgresql"
    assert called["schema"] == "public"
    assert result["success"] is True
    assert result["imported_tables"] == ["demo"]
    assert result["schema"] == "public"


def test_import_csv_dispatches_clickhouse_adapter_schema_empty(monkeypatch):
    called = {}
    import_dir = _make_import_dir()

    class DummyAdapter:
        def import_csv(
            self,
            client,
            db_config,
            table_names,
            data_dir,
            schema,
            pre_sql_file,
            need_backup,
            logger,
        ):
            called["schema"] = schema
            return {
                "success": False,
                "imported_tables": [],
                "error_tables": [{"table": "demo", "error": "boom"}],
                "backup_path": None,
                "data_directory": data_dir,
                "error": "boom",
                "schema": schema,
            }

    handle = ConnectionHandle(
        db_type="clickhouse",
        adapter=DummyAdapter(),
        client=object(),
    )

    monkeypatch.setattr("core.importer_csv.create_connection", lambda db_config, logger: handle)
    monkeypatch.setattr("core.importer_csv.close_connection", lambda conn, logger: None)
    monkeypatch.setattr("core.importer_csv.get_data_directory", lambda *args, **kwargs: import_dir)
    monkeypatch.setattr("core.importer_csv.get_table_names_from_csv", lambda data_dir: ["demo"])

    try:
        result = import_csv_to_db(
            db_config={
                "name": "ch",
                "db_type": "clickhouse",
                "host": "127.0.0.1",
                "database": "default",
                "user": "default",
                "password": "",
            },
            data_source=import_dir,
            source_type="folder",
            schema="public",
        )
    finally:
        import shutil
        shutil.rmtree(import_dir, ignore_errors=True)

    assert called["schema"] == ""
    assert result["success"] is False
    assert result["error_tables"][0]["table"] == "demo"
    assert result["schema"] == ""


def test_import_csv_result_passes_through_adapter(monkeypatch):
    import_dir = _make_import_dir()

    class DummyAdapter:
        def import_csv(
            self,
            client,
            db_config,
            table_names,
            data_dir,
            schema,
            pre_sql_file,
            need_backup,
            logger,
        ):
            return {
                "success": False,
                "imported_tables": [],
                "error_tables": [{"table": "demo", "error": "boom"}],
                "backup_path": None,
                "data_directory": data_dir,
                "error": "boom",
                "schema": schema,
            }

    handle = ConnectionHandle(
        db_type="postgresql",
        adapter=DummyAdapter(),
        client=object(),
    )

    monkeypatch.setattr("core.importer_csv.create_connection", lambda db_config, logger: handle)
    monkeypatch.setattr("core.importer_csv.close_connection", lambda conn, logger: None)
    monkeypatch.setattr("core.importer_csv.get_data_directory", lambda *args, **kwargs: import_dir)
    monkeypatch.setattr("core.importer_csv.get_table_names_from_csv", lambda data_dir: ["demo"])

    try:
        result = import_csv_to_db(
            db_config={
                "name": "pg",
                "db_type": "postgresql",
                "host": "127.0.0.1",
                "database": "postgres",
                "user": "postgres",
                "password": "",
            },
            data_source=import_dir,
            source_type="folder",
            schema="public",
        )
    finally:
        import shutil
        shutil.rmtree(import_dir, ignore_errors=True)

    assert result["success"] is False
    assert result["error_tables"][0]["error"] == "boom"
    assert result["schema"] == "public"


def test_import_csv_sets_data_directory_and_passes_params(monkeypatch):
    called = {}
    import_dir = _make_import_dir()

    class DummyAdapter:
        def import_csv(
            self,
            client,
            db_config,
            table_names,
            data_dir,
            schema,
            pre_sql_file,
            need_backup,
            logger,
        ):
            called["pre_sql_file"] = pre_sql_file
            called["need_backup"] = need_backup
            return {
                "success": True,
                "imported_tables": table_names,
                "error_tables": [],
                "backup_path": None,
                "schema": schema,
            }

    handle = ConnectionHandle(
        db_type="postgresql",
        adapter=DummyAdapter(),
        client=object(),
    )

    monkeypatch.setattr("core.importer_csv.create_connection", lambda db_config, logger: handle)
    monkeypatch.setattr("core.importer_csv.close_connection", lambda conn, logger: None)
    monkeypatch.setattr("core.importer_csv.get_data_directory", lambda *args, **kwargs: import_dir)
    monkeypatch.setattr("core.importer_csv.get_table_names_from_csv", lambda data_dir: ["demo"])

    try:
        result = import_csv_to_db(
            db_config={
                "name": "pg",
                "db_type": "postgresql",
                "host": "127.0.0.1",
                "database": "postgres",
                "user": "postgres",
                "password": "",
            },
            data_source=import_dir,
            source_type="folder",
            schema="public",
            pre_sql_file="pre.sql",
            need_backup=True,
        )
    finally:
        import shutil
        shutil.rmtree(import_dir, ignore_errors=True)

    assert called["pre_sql_file"] == "pre.sql"
    assert called["need_backup"] is True
    assert result["success"] is True
    assert result["data_directory"] == import_dir
    assert result["schema"] == "public"


def test_clickhouse_import_invalid_table_does_not_abort(monkeypatch):
    adapter = ClickHouseAdapter()

    invalid_table = "   "
    valid_table = "good_table"

    def fake_generate_copy_commands(table_names, data_dir):
        return [(invalid_table, "invalid.csv"), (valid_table, "valid.csv")]

    class DummyBinaryFile(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

    def fake_open(path, mode="rb"):
        return DummyBinaryFile(b"col1\n2\n")

    monkeypatch.setattr("db.adapters.clickhouse_adapter.generate_copy_commands", fake_generate_copy_commands)
    monkeypatch.setattr("builtins.open", fake_open)

    class DummyClient:
        def __init__(self):
            self.commands = []

        def command(self, statement, data=None):
            if data is not None and not isinstance(data, (str, bytes)):
                raise TypeError('data must be str or bytes')
            self.commands.append(statement)

    client = DummyClient()

    result = adapter.import_csv(
        client=client,
        db_config={
            "name": "ch",
            "db_type": "clickhouse",
            "host": "127.0.0.1",
            "database": "default",
            "user": "default",
            "password": "",
        },
        table_names=[invalid_table, valid_table],
        data_dir="ignored",
        schema="",
        pre_sql_file="",
        need_backup=False,
        logger=None,
    )

    assert any(item["table"] == invalid_table for item in result["error_tables"])
    assert valid_table in result["imported_tables"]
    assert result["schema"] == ""




def test_import_csv_postgresql_blank_schema_defaults_public(monkeypatch):
    called = {}
    import_dir = _make_import_dir()

    class DummyAdapter:
        def import_csv(
            self,
            client,
            db_config,
            table_names,
            data_dir,
            schema,
            pre_sql_file,
            need_backup,
            logger,
        ):
            called["schema"] = schema
            return {
                "success": True,
                "imported_tables": table_names,
                "error_tables": [],
                "backup_path": None,
                "data_directory": data_dir,
                "schema": schema,
            }

    handle = ConnectionHandle(
        db_type="postgresql",
        adapter=DummyAdapter(),
        client=object(),
    )

    monkeypatch.setattr("core.importer_csv.create_connection", lambda db_config, logger: handle)
    monkeypatch.setattr("core.importer_csv.close_connection", lambda conn, logger: None)
    monkeypatch.setattr("core.importer_csv.get_data_directory", lambda *args, **kwargs: import_dir)
    monkeypatch.setattr("core.importer_csv.get_table_names_from_csv", lambda data_dir: ["demo"])

    try:
        result = import_csv_to_db(
            db_config={
                "name": "pg",
                "db_type": "postgresql",
                "host": "127.0.0.1",
                "database": "postgres",
                "user": "postgres",
                "password": "",
                "schema": " \n\t",
            },
            data_source=import_dir,
            source_type="folder",
            schema=" \n\t",
        )
    finally:
        import shutil
        shutil.rmtree(import_dir, ignore_errors=True)

    assert called["schema"] == "public"
    assert result["schema"] == "public"


class _DummyCursorForPreSql:
    def __init__(self, executed):
        self.executed = executed
        self.rowcount = -1

    def execute(self, statement):
        self.executed.append(statement)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyClientForPreSql:
    def __init__(self):
        self.executed = []

    def cursor(self):
        return _DummyCursorForPreSql(self.executed)


def test_postgresql_pre_sql_handles_dollar_quotes():
    adapter = PostgreSQLAdapter()
    client = _DummyClientForPreSql()

    pre_sql = """
    CREATE OR REPLACE FUNCTION demo() RETURNS void AS $$
    BEGIN
        RAISE NOTICE 'hello; world';
    END;
    $$ LANGUAGE plpgsql;

    CREATE TABLE demo_table(id int);
    """

    adapter._execute_pre_sql(client, pre_sql, logger=None)

    assert len(client.executed) == 2
    assert client.executed[0].lstrip().startswith("CREATE OR REPLACE FUNCTION")
    assert client.executed[1].lstrip().startswith("CREATE TABLE")


class _DummyCursorForRollback:
    def __init__(self, table_to_fail):
        self.table_to_fail = table_to_fail
        self.rowcount = 0

    def execute(self, statement):
        if self.table_to_fail in statement:
            raise RuntimeError("copy failed")

    def copy_expert(self, statement, file_obj):
        if self.table_to_fail in statement:
            raise RuntimeError("copy failed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyClientForRollback:
    def __init__(self, table_to_fail):
        self.table_to_fail = table_to_fail
        self.autocommit = True
        self.rolled_back = False
        self.committed = False

    def cursor(self):
        return _DummyCursorForRollback(self.table_to_fail)

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        self.committed = True


def test_postgresql_import_rollback_clears_imported_tables(monkeypatch):
    adapter = PostgreSQLAdapter()
    client = _DummyClientForRollback(table_to_fail="table_b")

    monkeypatch.setattr(
        "db.adapters.postgresql_adapter.generate_copy_commands",
        lambda tables, data_dir: [("table_a", "a.csv"), ("table_b", "b.csv")],
    )
    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: io.StringIO("id\n1\n"),
    )
    monkeypatch.setattr(
        PostgreSQLAdapter,
        "_get_table_counts",
        staticmethod(lambda *args, **kwargs: {}),
    )

    result = adapter.import_csv(
        client=client,
        db_config={
            "name": "pg",
            "db_type": "postgresql",
            "host": "127.0.0.1",
            "database": "postgres",
            "user": "postgres",
            "password": "",
        },
        table_names=["table_a", "table_b"],
        data_dir=".",
        schema="public",
        pre_sql_file="",
        need_backup=False,
        logger=None,
    )

    assert result["success"] is False
    assert result["imported_tables"] == []
    assert client.rolled_back is True






def test_postgresql_import_uses_double_quote_escape():
    source = Path("db/adapters/postgresql_adapter.py").read_text(encoding="utf-8")
    assert r"ESCAPE '\"'" in source


def test_read_sql_from_file_accepts_uppercase_extension(monkeypatch):
    sql_path = "PRE.SQL"

    class DummyTextFile(io.StringIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

    monkeypatch.setattr("os.path.exists", lambda path: path == sql_path)
    monkeypatch.setattr("builtins.open", lambda path, mode="r", encoding=None: DummyTextFile("SELECT 1;"))

    from core.importer_csv import read_sql_from_file
    assert read_sql_from_file(sql_path) == "SELECT 1;"


def test_clickhouse_split_sql_statements_keeps_semicolons_inside_strings():
    statements = ClickHouseAdapter._split_sql_statements("SELECT ';';\nSELECT 2;")
    assert statements == ["SELECT ';'", "SELECT 2"]


def test_clickhouse_export_sql_no_tables_returns_clean_error():
    adapter = ClickHouseAdapter()

    class DummyResult:
        def __init__(self, rows):
            self.result_rows = rows

    class DummyClient:
        def query(self, statement):
            if statement == "SHOW TABLES FROM `default`":
                return DummyResult([])
            raise AssertionError(f"unexpected statement: {statement}")

    result = adapter.export_sql(
        client=DummyClient(),
        db_config={
            "name": "ch",
            "db_type": "clickhouse",
            "host": "127.0.0.1",
            "database": "default",
            "user": "default",
            "password": "",
        },
        export_dir=".",
        schema="public",
        exclude_tables=[],
        include_truncate=True,
        logger=None,
    )

    assert result["success"] is False
    assert result["schema"] == ""
    assert "No exportable tables found" == result["error"]


def test_clickhouse_export_sql_orders_tables_and_ignores_schema():
    adapter = ClickHouseAdapter()

    class DummyResult:
        def __init__(self, rows, column_names=None):
            self.result_rows = rows
            self.column_names = column_names or []

    class DummyClient:
        def query(self, statement):
            if statement == "SHOW TABLES FROM `default`":
                return DummyResult([("z_table",), ("skip_me",), ("a_table",)])
            if statement == "SHOW CREATE TABLE `default`.`a_table`":
                return DummyResult([("CREATE TABLE `default`.`a_table` (`id` UInt32) ENGINE = MergeTree ORDER BY tuple()",)])
            if statement == "SHOW CREATE TABLE `default`.`z_table`":
                return DummyResult([("CREATE TABLE `default`.`z_table` (`id` UInt32) ENGINE = MergeTree ORDER BY tuple()",)])
            if statement == "SELECT * FROM `default`.`a_table`":
                return DummyResult([(1,)], ["id"])
            if statement == "SELECT * FROM `default`.`z_table`":
                return DummyResult([(2,)], ["id"])
            raise AssertionError(f"unexpected statement: {statement}")

    result = adapter.export_sql(
        client=DummyClient(),
        db_config={
            "name": "ch",
            "db_type": "clickhouse",
            "host": "127.0.0.1",
            "database": "default",
            "user": "default",
            "password": "",
        },
        export_dir=".",
        schema="public",
        exclude_tables=["skip_me"],
        include_truncate=True,
        logger=None,
    )

    try:
        assert result["success"] is True
        assert result["schema"] == ""
        assert Path(result["export_file"]).name.startswith("default_")
        assert "public" not in Path(result["export_file"]).name

        content = Path(result["export_file"]).read_text(encoding="utf-8")
        assert "skip_me" not in content
        assert content.index("`a_table`") < content.index("`z_table`")
        assert "TRUNCATE TABLE `default`.`a_table`;" in content
        assert "INSERT INTO `default`.`a_table` (`id`) VALUES (1);" in content
        assert "INSERT INTO `default`.`z_table` (`id`) VALUES (2);" in content
    finally:
        export_file = result.get("export_file")
        if export_file:
            Path(export_file).unlink(missing_ok=True)


def test_pyinstaller_spec_includes_clickhouse_hidden_import():
    spec_files = list(Path(".").glob("*.spec"))
    assert spec_files, "spec file not found"
    spec_source = spec_files[0].read_text(encoding="utf-8")
    assert "clickhouse_connect" in spec_source



def test_clickhouse_import_creates_csv_backup_before_import(monkeypatch):
    adapter = ClickHouseAdapter()

    class DummyBinaryFile(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

    written = {}

    class DummyWriteFile(io.BytesIO):
        def __init__(self, path):
            super().__init__()
            self._path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            written[self._path] = self.getvalue()
            self.close()
            return False

    def fake_open(path, mode='r', encoding=None):
        path_str = str(path)
        if 'rb' in mode:
            return DummyBinaryFile(b'id\n2\n')
        if 'wb' in mode:
            return DummyWriteFile(path_str)
        raise AssertionError(f'unexpected open mode: {mode}')

    monkeypatch.setattr('db.adapters.clickhouse_adapter.generate_copy_commands', lambda tables, data_dir: [('demo', 'demo.csv')])
    monkeypatch.setattr('builtins.open', fake_open)

    class DummyClient:
        def __init__(self):
            self.commands = []

        def raw_query(self, statement):
            if statement == 'SELECT * FROM `default`.`demo` FORMAT CSVWithNames':
                return b'id\n1\n'
            raise AssertionError(f'unexpected raw_query: {statement}')

        def command(self, statement, data=None):
            self.commands.append((statement, data))

    client = DummyClient()

    result = adapter.import_csv(
        client=client,
        db_config={
            'name': 'ch',
            'db_type': 'clickhouse',
            'host': '127.0.0.1',
            'database': 'default',
            'user': 'default',
            'password': '',
        },
        table_names=['demo'],
        data_dir='data_dir',
        schema='',
        pre_sql_file='',
        need_backup=True,
        logger=None,
    )

    assert result['success'] is True
    assert result['backup_path']
    assert any(path.endswith('demo.csv') for path in written)
    assert any(data == b'id\n2\n' for _, data in client.commands if data is not None)


def test_clickhouse_import_backup_failure_stops_import(monkeypatch):
    adapter = ClickHouseAdapter()

    monkeypatch.setattr('db.adapters.clickhouse_adapter.generate_copy_commands', lambda tables, data_dir: [('demo', 'demo.csv')])

    class DummyClient:
        def __init__(self):
            self.commands = []

        def raw_query(self, statement):
            raise RuntimeError('backup failed')

        def command(self, statement, data=None):
            self.commands.append((statement, data))

    result = adapter.import_csv(
        client=DummyClient(),
        db_config={
            'name': 'ch',
            'db_type': 'clickhouse',
            'host': '127.0.0.1',
            'database': 'default',
            'user': 'default',
            'password': '',
        },
        table_names=['demo'],
        data_dir='data_dir',
        schema='',
        pre_sql_file='',
        need_backup=True,
        logger=None,
    )

    assert result['success'] is False
    assert result['backup_path'] is None
    assert result['error'] == ''.join(chr(x) for x in [23548, 20837, 21069, 22791, 20221, 22833, 36133]) + ': backup failed'
    assert result['error_tables'] == []
    assert result['imported_tables'] == []
