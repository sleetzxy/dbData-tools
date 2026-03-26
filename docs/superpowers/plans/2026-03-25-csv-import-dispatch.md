# CSV Import Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor CSV import to dispatch by database adapter while preserving existing result structures and adding ClickHouse support.

**Architecture:** Keep ZIP/folder extraction and CSV file discovery in `core/importer_csv.py`, then delegate database-specific truncate/import/count/backup logic to adapter methods. PostgreSQL and ClickHouse adapters implement `import_csv` with different transaction semantics; core orchestrates and aggregates results without touching DB-specific SQL.

**Tech Stack:** Python, psycopg2 (PostgreSQL), clickhouse-connect (ClickHouse), pytest.

---

## File Structure & Responsibilities
- `core/importer_csv.py`: Orchestrate CSV import flow, file discovery, pre-SQL reading, and call adapter.import_csv. Maintain existing result structure and metadata fields.
- `db/adapters/postgresql_adapter.py`: Implement PostgreSQL CSV import logic (truncate, copy, counts, optional backup, transactional behavior).
- `db/adapters/clickhouse_adapter.py`: Implement ClickHouse CSV import logic (truncate + insert, per-table success tracking, no global transaction).
- `gui/pages/csv/importer.py`: Minimal updates if any to accommodate new result fields or schema behavior.
- `tests/test_adapter_dispatch.py`: Add tests for CSV import dispatch and result aggregation, mocking adapter methods.

---

### Task 1: Add failing tests for CSV import dispatch + aggregation

**Files:**
- Modify: `tests/test_adapter_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
def test_import_csv_dispatches_postgresql_adapter(monkeypatch, tmp_path):
    called = {}

    class DummyHandle:
        def __init__(self):
            self.db_type = "postgresql"
            self.adapter = DummyAdapter()
            self.client = object()

    class DummyAdapter:
        def import_csv(self, client, db_config, table_names, data_dir, schema, pre_sql_file, need_backup, logger):
            called["adapter"] = "postgresql"
            return {
                "success": True,
                "imported_tables": ["demo"],
                "error_tables": [],
                "backup_path": None,
                "data_directory": data_dir,
            }

    monkeypatch.setattr("core.importer_csv.create_connection", lambda db_config, logger: DummyHandle())
    monkeypatch.setattr("core.importer_csv.close_connection", lambda conn, logger: None)
    monkeypatch.setattr("core.importer_csv.get_data_directory", lambda *args, **kwargs: str(tmp_path))
    monkeypatch.setattr("core.importer_csv.get_table_names_from_csv", lambda data_dir: ["demo"])

    result = import_csv_to_db(
        db_config={"db_type": "postgresql", "host": "", "database": "", "user": "", "password": ""},
        data_source=str(tmp_path),
        source_type="folder",
        schema="public",
    )

    assert called["adapter"] == "postgresql"
    assert result["success"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_dispatch.py::test_import_csv_dispatches_postgresql_adapter -v`
Expected: FAIL (import_csv_to_db doesn¡¯t call adapter.import_csv yet)

- [ ] **Step 3: Add ClickHouse dispatch + schema handling test**

```python
def test_import_csv_dispatches_clickhouse_adapter_schema_empty(monkeypatch, tmp_path):
    called = {}

    class DummyHandle:
        def __init__(self):
            self.db_type = "clickhouse"
            self.adapter = DummyAdapter()
            self.client = object()

    class DummyAdapter:
        def import_csv(self, client, db_config, table_names, data_dir, schema, pre_sql_file, need_backup, logger):
            called["schema"] = schema
            return {
                "success": False,
                "imported_tables": [],
                "error_tables": [{"schema": "", "name": "demo", "error": "boom"}],
                "backup_path": None,
                "data_directory": data_dir,
                "error": "boom",
            }

    monkeypatch.setattr("core.importer_csv.create_connection", lambda db_config, logger: DummyHandle())
    monkeypatch.setattr("core.importer_csv.close_connection", lambda conn, logger: None)
    monkeypatch.setattr("core.importer_csv.get_data_directory", lambda *args, **kwargs: str(tmp_path))
    monkeypatch.setattr("core.importer_csv.get_table_names_from_csv", lambda data_dir: ["demo"])

    result = import_csv_to_db(
        db_config={"db_type": "clickhouse", "host": "", "database": "", "user": "", "password": ""},
        data_source=str(tmp_path),
        source_type="folder",
        schema="public",
    )

    assert called["schema"] == ""
    assert result["schema"] == ""
    assert result["success"] is False
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_adapter_dispatch.py::test_import_csv_dispatches_clickhouse_adapter_schema_empty -v`
Expected: FAIL (schema not normalized and dispatch not in place)

- [ ] **Step 5: Commit**

```bash
git add tests/test_adapter_dispatch.py
git commit -m "test: cover csv import adapter dispatch"
```

---

### Task 2: Implement PostgreSQL adapter CSV import

**Files:**
- Modify: `db/adapters/postgresql_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
def test_postgresql_adapter_import_csv_preserves_result_shape(monkeypatch, tmp_path):
    adapter = PostgreSQLAdapter()

    class DummyCursor:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def execute(self, *args, **kwargs):
            return None
        def copy_expert(self, *args, **kwargs):
            return None
        def fetchall(self):
            return [("demo", 1)]
        @property
        def rowcount(self):
            return 1

    class DummyConn:
        def __init__(self):
            self.autocommit = False
        def cursor(self):
            return DummyCursor()
        def commit(self):
            return None
        def rollback(self):
            return None

    monkeypatch.setattr("core.importer_csv.generate_copy_commands", lambda tables, data_dir: [("demo", str(tmp_path / "demo.csv"))])
    (tmp_path / "demo.csv").write_text("id\n1\n", encoding="utf-8")

    result = adapter.import_csv(
        DummyConn(),
        db_config={"database": "db"},
        table_names=["demo"],
        data_dir=str(tmp_path),
        schema="public",
        pre_sql_file="",
        need_backup=False,
        logger=None,
    )

    assert "imported_tables" in result
    assert result["success"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_dispatch.py::test_postgresql_adapter_import_csv_preserves_result_shape -v`
Expected: FAIL (adapter.import_csv not implemented)

- [ ] **Step 3: Implement PostgreSQL adapter import_csv**

```python
def import_csv(
    self,
    client,
    db_config,
    table_names,
    data_dir,
    schema="public",
    pre_sql_file="",
    need_backup=False,
    logger=None,
):
    result = {
        "success": True,
        "imported_tables": [],
        "error_tables": [],
        "backup_path": None,
        "data_directory": data_dir,
        "schema": schema,
    }
    # reuse existing helper functions from core.importer_csv via imports
    # execute pre_sql, counts, backup, truncate/copy, commit/rollback
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapter_dispatch.py::test_postgresql_adapter_import_csv_preserves_result_shape -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db/adapters/postgresql_adapter.py
git commit -m "feat: move postgresql csv import into adapter"
```

---

### Task 3: Implement ClickHouse adapter CSV import

**Files:**
- Modify: `db/adapters/clickhouse_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
def test_clickhouse_adapter_import_csv_tracks_per_table(monkeypatch, tmp_path):
    adapter = ClickHouseAdapter()

    class DummyClient:
        def __init__(self):
            self.commands = []
        def command(self, sql, data=None):
            self.commands.append(sql)

    csv_path = tmp_path / "demo.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")

    result = adapter.import_csv(
        DummyClient(),
        db_config={"database": "default"},
        table_names=["demo"],
        data_dir=str(tmp_path),
        schema="public",
        pre_sql_file="",
        need_backup=False,
        logger=None,
    )

    assert result["schema"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_dispatch.py::test_clickhouse_adapter_import_csv_tracks_per_table -v`
Expected: FAIL (adapter.import_csv not implemented)

- [ ] **Step 3: Implement ClickHouse adapter import_csv**

```python
def import_csv(
    self,
    client,
    db_config,
    table_names,
    data_dir,
    schema="",
    pre_sql_file="",
    need_backup=False,
    logger=None,
):
    # schema ignored
    database = self._validate_identifier(str(db_config.get("database", "")).strip(), "database")
    result = {
        "success": True,
        "imported_tables": [],
        "error_tables": [],
        "backup_path": None,
        "data_directory": data_dir,
        "schema": "",
    }
    # use generate_copy_commands to find csv files
    # per table: TRUNCATE TABLE database.table; INSERT INTO database.table FORMAT CSVWithNames
    # on error: append error_tables with schema "" and name; keep success False but continue
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapter_dispatch.py::test_clickhouse_adapter_import_csv_tracks_per_table -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db/adapters/clickhouse_adapter.py
git commit -m "feat: add clickhouse csv import"
```

---

### Task 4: Update core importer orchestrator to dispatch via adapter

**Files:**
- Modify: `core/importer_csv.py`

- [ ] **Step 1: Write the failing test**

```python
def test_import_csv_result_aggregation_passes_through_adapter(monkeypatch, tmp_path):
    class DummyAdapter:
        def import_csv(self, client, db_config, table_names, data_dir, schema, pre_sql_file, need_backup, logger):
            return {
                "success": False,
                "imported_tables": [],
                "error_tables": [{"schema": schema, "name": "demo", "error": "boom"}],
                "backup_path": None,
                "data_directory": data_dir,
                "schema": schema,
                "error": "boom",
            }

    handle = ConnectionHandle(db_type="postgresql", adapter=DummyAdapter(), client=object())

    monkeypatch.setattr("core.importer_csv.create_connection", lambda db_config, logger: handle)
    monkeypatch.setattr("core.importer_csv.close_connection", lambda conn, logger: None)
    monkeypatch.setattr("core.importer_csv.get_data_directory", lambda *args, **kwargs: str(tmp_path))
    monkeypatch.setattr("core.importer_csv.get_table_names_from_csv", lambda data_dir: ["demo"])

    result = import_csv_to_db(
        db_config={"db_type": "postgresql", "host": "", "database": "", "user": "", "password": ""},
        data_source=str(tmp_path),
        source_type="folder",
        schema="public",
    )

    assert result["success"] is False
    assert result["error_tables"][0]["name"] == "demo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_dispatch.py::test_import_csv_result_aggregation_passes_through_adapter -v`
Expected: FAIL

- [ ] **Step 3: Update importer_csv.import_csv_to_db to orchestrate only**

```python
handle = create_connection(db_config, logger)
if not handle:
    # return error, ensure schema empty for clickhouse
adapter = handle.adapter
schema = "" if handle.db_type == "clickhouse" else schema
result = adapter.import_csv(
    handle.client,
    db_config=db_config,
    table_names=table_names,
    data_dir=data_dir,
    schema=schema,
    pre_sql_file=pre_sql_file,
    need_backup=need_backup,
    logger=logger,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapter_dispatch.py::test_import_csv_result_aggregation_passes_through_adapter -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/importer_csv.py
git commit -m "refactor: dispatch csv import via adapter"
```

---

### Task 5: GUI stability check + full test pass

**Files:**
- Modify (if needed): `gui/pages/csv/importer.py`

- [ ] **Step 1: Run targeted tests**

Run: `pytest tests/test_adapter_dispatch.py -v`
Expected: PASS

- [ ] **Step 2: Compile check**

Run: `python -m compileall core db gui utils main_gui.py`
Expected: no syntax errors

- [ ] **Step 3: Manual sanity**

Run: `python main_gui.py`
Expected: CSV import page loads and no errors selecting ClickHouse connection.

- [ ] **Step 4: Commit**

```bash
git add gui/pages/csv/importer.py
git commit -m "chore: keep csv importer stable"
```

---

## Plan Review Loop
- [ ] Dispatch plan-document-reviewer subagent with:
  - Plan path: `docs/superpowers/plans/2026-03-25-csv-import-dispatch.md`
  - Spec context: Task 5 instructions from user message
- [ ] If issues found, revise and re-dispatch
- [ ] If approved, proceed to execution handoff

---

## Execution Handoff
Plan complete and saved to `docs/superpowers/plans/2026-03-25-csv-import-dispatch.md`.

Two execution options:
1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** - Execute tasks in this session using executing-plans.

Which approach?
