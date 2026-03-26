# Task 5 PostgreSQL Import Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize PostgreSQL schema defaults, fix pre-SQL parsing for $$ blocks, and ensure rollback clears reported imports for Task 5.

**Architecture:** Update the core CSV import dispatcher to normalize PostgreSQL schema values before adapter dispatch and result shaping. Replace the PostgreSQL pre-SQL splitter with a dollar-quote aware statement parser. Ensure PostgreSQL import rollback clears `imported_tables` when any table fails. Tests in `tests/test_adapter_dispatch.py` will lock behavior with mocks.

**Tech Stack:** Python, pytest, psycopg2 adapter mocks.

---

## File/Module Map

- `core/importer_csv.py`: Normalize PostgreSQL schema inputs/outputs before calling adapter.
- `db/adapters/postgresql_adapter.py`: Replace `_execute_pre_sql` parser; clear `imported_tables` on rollback.
- `gui/pages/csv/importer.py`: Verify if schema normalization needs UI-level fallback (only adjust if required by tests/spec).
- `tests/test_adapter_dispatch.py`: Add tests for schema normalization, pre-SQL parsing with $$ blocks, and rollback semantics (if needed).

---

### Task 1: Add schema normalization test for PostgreSQL import dispatch

**Files:**
- Modify: `tests/test_adapter_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
def test_import_csv_postgresql_blank_schema_defaults_public(monkeypatch):
    called = {}

    class DummyAdapter:
        def import_csv(self, client, db_config, table_names, data_dir, schema, pre_sql_file, need_backup, logger):
            called["schema"] = schema
            return {
                "success": True,
                "imported_tables": table_names,
                "error_tables": [],
                "backup_path": None,
                "data_directory": data_dir,
                "schema": schema,
            }

    handle = ConnectionHandle(db_type="postgresql", adapter=DummyAdapter(), client=object())

    monkeypatch.setattr("core.importer_csv.create_connection", lambda db_config, logger: handle)
    monkeypatch.setattr("core.importer_csv.close_connection", lambda conn, logger: None)
    monkeypatch.setattr("core.importer_csv.get_data_directory", lambda *args, **kwargs: ".")
    monkeypatch.setattr("core.importer_csv.get_table_names_from_csv", lambda data_dir: ["demo"])

    result = import_csv_to_db(
        db_config={
            "name": "pg",
            "db_type": "postgresql",
            "host": "127.0.0.1",
            "database": "postgres",
            "user": "postgres",
            "password": "",
            "schema": "",
        },
        data_source=".",
        source_type="folder",
        schema="",
    )

    assert called["schema"] == "public"
    assert result["schema"] == "public"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_dispatch.py::test_import_csv_postgresql_blank_schema_defaults_public -v`
Expected: FAIL (schema is empty instead of `public`).

---

### Task 2: Add pre-SQL $$ parser test for PostgreSQL

**Files:**
- Modify: `tests/test_adapter_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
class DummyCursor:
    def __init__(self, executed):
        self.executed = executed
        self.rowcount = -1

    def execute(self, statement):
        self.executed.append(statement)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyClient:
    def __init__(self):
        self.executed = []

    def cursor(self):
        return DummyCursor(self.executed)


def test_postgresql_pre_sql_handles_dollar_quotes():
    adapter = PostgreSQLAdapter()
    client = DummyClient()

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
    assert client.executed[0].startswith("CREATE OR REPLACE FUNCTION")
    assert client.executed[1].startswith("CREATE TABLE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_dispatch.py::test_postgresql_pre_sql_handles_dollar_quotes -v`
Expected: FAIL (current parser splits function body incorrectly).

---

### Task 3: Add rollback semantics test for PostgreSQL import

**Files:**
- Modify: `tests/test_adapter_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
class DummyCursor:
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


class DummyClient:
    def __init__(self, table_to_fail):
        self.table_to_fail = table_to_fail
        self.autocommit = True
        self.rolled_back = False
        self.committed = False

    def cursor(self):
        return DummyCursor(self.table_to_fail)

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        self.committed = True


def test_postgresql_import_rollback_clears_imported_tables(monkeypatch):
    adapter = PostgreSQLAdapter()
    client = DummyClient(table_to_fail="table_b")

    monkeypatch.setattr("db.adapters.postgresql_adapter.generate_copy_commands", lambda tables, data_dir: [("table_a", "a.csv"), ("table_b", "b.csv")])
    monkeypatch.setattr("db.adapters.postgresql_adapter.open", lambda *args, **kwargs: io.StringIO("id\n1\n"))
    monkeypatch.setattr(PostgreSQLAdapter, "_get_table_counts", staticmethod(lambda *args, **kwargs: {}))

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_dispatch.py::test_postgresql_import_rollback_clears_imported_tables -v`
Expected: FAIL (imported_tables still contains table_a).

---

### Task 4: Normalize PostgreSQL schema in CSV import dispatch

**Files:**
- Modify: `core/importer_csv.py`
- Modify: `gui/pages/csv/importer.py` (only if normalization must happen earlier for UI state)

- [ ] **Step 1: Update schema normalization logic**

```python
if db_config.get("db_type") == "postgresql":
    normalized_schema = schema or "public"
else:
    normalized_schema = "" if db_config.get("db_type") == "clickhouse" else schema
```

- [ ] **Step 2: Ensure adapter dispatch uses normalized schema and result schema defaults back to it**

```python
adapter_schema = "" if conn.db_type == "clickhouse" else normalized_schema
...
if not result.get("schema"):
    result["schema"] = normalized_schema
```

- [ ] **Step 3: Run schema test**

Run: `pytest tests/test_adapter_dispatch.py::test_import_csv_postgresql_blank_schema_defaults_public -v`
Expected: PASS.

---

### Task 5: Replace PostgreSQL pre-SQL parser with dollar-quote aware splitter

**Files:**
- Modify: `db/adapters/postgresql_adapter.py`

- [ ] **Step 1: Implement a tokenizer that splits on semicolons outside strings/comments/dollar-quoted blocks**

```python
def _split_sql_statements(sql_text: str) -> List[str]:
    statements = []
    buf = []
    i = 0
    in_single = in_double = False
    in_line_comment = in_block_comment = False
    dollar_tag = None

    while i < len(sql_text):
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < len(sql_text) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                buf.append(ch)
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if dollar_tag is not None:
            if sql_text.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(ch)
            i += 1
            continue

        if not in_single and not in_double and ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue

        if not in_single and not in_double and ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue

        if not in_double and ch == "'":
            if in_single and nxt == "'":
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue

        if not in_single and ch == '"':
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue

        if not in_single and not in_double and ch == "$":
            end = sql_text.find("$", i + 1)
            if end != -1:
                tag = sql_text[i:end + 1]
                if tag.strip("$") == "" or tag.strip("$").replace("_", "").isalnum():
                    dollar_tag = tag
                    buf.append(tag)
                    i = end + 1
                    continue

        if ch == ";" and not in_single and not in_double and dollar_tag is None:
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    trailing = "".join(buf).strip()
    if trailing:
        statements.append(trailing)

    return [stmt for stmt in statements if stmt and not stmt.upper().startswith("DELIMITER ")]
```

- [ ] **Step 2: Use the splitter in `_execute_pre_sql` and keep logging**

- [ ] **Step 3: Run pre-SQL test**

Run: `pytest tests/test_adapter_dispatch.py::test_postgresql_pre_sql_handles_dollar_quotes -v`
Expected: PASS.

---

### Task 6: Clear `imported_tables` when PostgreSQL import rolls back

**Files:**
- Modify: `db/adapters/postgresql_adapter.py`

- [ ] **Step 1: After rollback, clear `imported_tables`**

```python
if not result["success"]:
    client.rollback()
    result["imported_tables"] = []
```

- [ ] **Step 2: Ensure exception rollback also clears `imported_tables`**

```python
except Exception as exc:
    ...
    result["success"] = False
    result["imported_tables"] = []
    try:
        client.rollback()
    except Exception:
        pass
```

- [ ] **Step 3: Run rollback test**

Run: `pytest tests/test_adapter_dispatch.py::test_postgresql_import_rollback_clears_imported_tables -v`
Expected: PASS.

---

### Task 7: Full test pass

**Files:**
- Test: `tests/test_adapter_dispatch.py`

- [ ] **Step 1: Run full test file**

Run: `pytest tests/test_adapter_dispatch.py -v`
Expected: PASS.

---
