# ClickHouse Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ClickHouse support alongside PostgreSQL for connection management, CSV import/export, and SQL export without breaking existing PostgreSQL behavior.

**Architecture:** Keep the current GUI flow, add `db_type` to persisted connection configs, and introduce database-specific adapter modules for PostgreSQL and ClickHouse. The `core` modules become orchestration layers that dispatch to the correct adapter based on `db_type`, while the connection management UI exposes the database type and preserves backward compatibility for old saved connections.

**Tech Stack:** Python, Tkinter/customtkinter, psycopg2, clickhouse-connect, pytest (targeted unit tests), compileall for syntax verification.

---

## File Structure / Responsibilities

- Modify: `db/connection.py` — normalize `db_type`, create/close database clients, expose adapter lookup helpers
- Create: `db/adapters/__init__.py` — adapter registry and shared helper exports
- Create: `db/adapters/postgresql_adapter.py` — PostgreSQL CSV import/export and SQL export behavior
- Create: `db/adapters/clickhouse_adapter.py` — ClickHouse CSV import/export and SQL export behavior
- Modify: `core/importer_csv.py` — import flow orchestration by `db_type`
- Modify: `core/exporter_csv.py` — export flow orchestration by `db_type`
- Modify: `core/exporter_db.py` — SQL export orchestration by `db_type`
- Modify: `gui/pages/management/connection.py` — add database type field, defaults, compatibility migration, type column
- Modify: `gui/components/connection_selector.py` — keep displaying saved connections correctly when type metadata is present
- Modify: `gui/pages/csv/importer.py` — ensure schema/default handling remains valid for ClickHouse
- Modify: `gui/pages/csv/exporter.py` — ensure selected connection config flows through unchanged
- Modify: `gui/pages/database/exporter.py` — ensure selected connection config flows through unchanged
- Create: `tests/test_connection_config.py` — compatibility tests for legacy connections and `db_type` defaults
- Create: `tests/test_adapter_dispatch.py` — dispatch tests for import/export/sql-export adapter selection

### Task 1: Add connection config typing and compatibility normalization

**Files:**
- Modify: `db/connection.py`
- Modify: `gui/pages/management/connection.py`
- Test: `tests/test_connection_config.py`

- [ ] **Step 1: Write failing tests for connection normalization**

Cover these cases in `tests/test_connection_config.py`:
- legacy config without `db_type` defaults to `postgresql`
- PostgreSQL default port/schema normalization
- ClickHouse default port normalization and schema ignored/empty behavior

- [ ] **Step 2: Run the new test file to confirm the baseline fails**

Run: `python -m pytest tests/test_connection_config.py -v`

- [ ] **Step 3: Add normalization helpers in `db/connection.py`**

Implement focused helpers such as:
- `get_db_type(db_config)`
- `normalize_connection_config(db_config)`
- `get_default_port(db_type)`

Require unknown `db_type` to fail explicitly.

- [ ] **Step 4: Update connection loading/saving in `gui/pages/management/connection.py`**

Make form save `db_type`, and make loaded connection rows auto-fill missing `db_type` as `postgresql` before rendering.

- [ ] **Step 5: Re-run the normalization tests**

Run: `python -m pytest tests/test_connection_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add db/connection.py gui/pages/management/connection.py tests/test_connection_config.py
git commit -m "feat: add database type to saved connections"
```

### Task 2: Add the connection management UI for database type

**Files:**
- Modify: `gui/pages/management/connection.py`

- [ ] **Step 1: Add the database type field to the add/edit dialog**

Add a dropdown with `postgresql` and `clickhouse` values. Keep display labels human-readable, but save normalized lowercase values.

- [ ] **Step 2: Add default-value switching logic**

When type changes:
- PostgreSQL -> port `5432`, schema `public`
- ClickHouse -> port `8123`, schema blank or disabled

Only apply defaults when the user has not already entered a custom value during the current edit session.

- [ ] **Step 3: Add a type column to the connection list**

Render type in the table/list so multiple connection kinds are distinguishable.

- [ ] **Step 4: Manually verify the dialog behavior**

Run: `python main_gui.py`
Check: create/edit PostgreSQL and ClickHouse connections, switch type, verify persisted values in `~/.connections.json`.

- [ ] **Step 5: Commit**

```bash
git add gui/pages/management/connection.py
git commit -m "feat: add database type selection to connection manager"
```

### Task 3: Introduce adapter modules and connection factory support

**Files:**
- Create: `db/adapters/__init__.py`
- Create: `db/adapters/postgresql_adapter.py`
- Create: `db/adapters/clickhouse_adapter.py`
- Modify: `db/connection.py`
- Test: `tests/test_adapter_dispatch.py`

- [ ] **Step 1: Write failing adapter dispatch tests**

In `tests/test_adapter_dispatch.py`, assert that PostgreSQL configs route to the PostgreSQL adapter and ClickHouse configs route to the ClickHouse adapter.

- [ ] **Step 2: Run the adapter dispatch tests to confirm failure**

Run: `python -m pytest tests/test_adapter_dispatch.py -v`

- [ ] **Step 3: Create adapter registry and shared interface shape**

Each adapter should expose a small, consistent surface for:
- client creation
- client close
- CSV export
- CSV import
- SQL export

- [ ] **Step 4: Extend `db/connection.py` to create the right client**

Use:
- `psycopg2.connect(...)` for PostgreSQL
- `clickhouse_connect.get_client(...)` for ClickHouse

Make close logic safe for both types.

- [ ] **Step 5: Re-run dispatch tests**

Run: `python -m pytest tests/test_adapter_dispatch.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add db/connection.py db/adapters/__init__.py db/adapters/postgresql_adapter.py db/adapters/clickhouse_adapter.py tests/test_adapter_dispatch.py
git commit -m "feat: add database adapter registry"
```

### Task 4: Refactor CSV export to dispatch by database type

**Files:**
- Modify: `core/exporter_csv.py`
- Modify: `db/adapters/postgresql_adapter.py`
- Modify: `db/adapters/clickhouse_adapter.py`
- Modify: `gui/pages/csv/exporter.py`

- [ ] **Step 1: Write or extend tests for CSV export dispatch**

Add unit coverage that `export_tables_to_csv(...)` calls the correct adapter implementation based on `db_config['db_type']`.

- [ ] **Step 2: Run the targeted tests and confirm failure**

Run: `python -m pytest tests/test_adapter_dispatch.py -v`

- [ ] **Step 3: Move PostgreSQL CSV export logic into its adapter**

Extract the current PostgreSQL `COPY ... TO STDOUT` behavior into `db/adapters/postgresql_adapter.py` with no behavior change.

- [ ] **Step 4: Implement ClickHouse CSV export**

Use `clickhouse-connect` to execute `SELECT * FROM database.table FORMAT CSVWithNames` and write the result to the requested CSV file.

- [ ] **Step 5: Update `core/exporter_csv.py` to orchestrate only**

Keep the existing return shape (`success`, `exported_tables`, `error_tables`, `total_rows`, `schema`) so GUI callers remain stable.

- [ ] **Step 6: Verify tests and perform a manual GUI smoke test**

Run:
- `python -m pytest tests/test_adapter_dispatch.py -v`
- `python main_gui.py`

Check: PostgreSQL export still works; ClickHouse export runs and writes CSV with header behavior preserved.

- [ ] **Step 7: Commit**

```bash
git add core/exporter_csv.py db/adapters/postgresql_adapter.py db/adapters/clickhouse_adapter.py gui/pages/csv/exporter.py tests/test_adapter_dispatch.py
git commit -m "feat: add clickhouse csv export support"
```

### Task 5: Refactor CSV import to dispatch by database type

**Files:**
- Modify: `core/importer_csv.py`
- Modify: `db/adapters/postgresql_adapter.py`
- Modify: `db/adapters/clickhouse_adapter.py`
- Modify: `gui/pages/csv/importer.py`

- [ ] **Step 1: Add or extend tests for CSV import dispatch**

Cover the adapter selection and result aggregation path. Mock adapter methods rather than requiring live databases.

- [ ] **Step 2: Run targeted tests to confirm failure**

Run: `python -m pytest tests/test_adapter_dispatch.py -v`

- [ ] **Step 3: Move PostgreSQL CSV import behavior into the PostgreSQL adapter**

Preserve ZIP/folder extraction and shared file discovery in `core/importer_csv.py`, but move database-specific truncate/import/count/backup operations behind adapter methods.

- [ ] **Step 4: Implement ClickHouse CSV import**

Use `TRUNCATE TABLE database.table` and `INSERT INTO database.table FORMAT CSVWithNames`. Treat success/failure per table; do not model ClickHouse imports as a PostgreSQL-style all-or-nothing transaction.

- [ ] **Step 5: Update `core/importer_csv.py` orchestration**

Keep the existing result structure so the GUI page does not need redesign.

- [ ] **Step 6: Verify tests and run a manual smoke test**

Run:
- `python -m pytest tests/test_adapter_dispatch.py -v`
- `python main_gui.py`

Check: PostgreSQL import behavior unchanged; ClickHouse import reports table-level failures clearly.

- [ ] **Step 7: Commit**

```bash
git add core/importer_csv.py db/adapters/postgresql_adapter.py db/adapters/clickhouse_adapter.py gui/pages/csv/importer.py tests/test_adapter_dispatch.py
git commit -m "feat: add clickhouse csv import support"
```

### Task 6: Refactor SQL export to dispatch by database type

**Files:**
- Modify: `core/exporter_db.py`
- Modify: `db/adapters/postgresql_adapter.py`
- Modify: `db/adapters/clickhouse_adapter.py`
- Modify: `gui/pages/database/exporter.py`

- [ ] **Step 1: Add or extend tests for SQL export dispatch**

Cover adapter routing and output contract at the orchestration layer.

- [ ] **Step 2: Run targeted tests to confirm failure**

Run: `python -m pytest tests/test_adapter_dispatch.py -v`

- [ ] **Step 3: Preserve PostgreSQL SQL export in the PostgreSQL adapter**

Move the current behavior into the adapter with minimal output changes.

- [ ] **Step 4: Implement ClickHouse SQL export**

For each table:
- fetch DDL with `SHOW CREATE TABLE database.table`
- optionally emit `TRUNCATE TABLE`
- fetch rows and serialize them as `INSERT INTO ... VALUES (...)`

Write a single `.sql` file with deterministic ordering.

- [ ] **Step 5: Update `core/exporter_db.py` to orchestrate by adapter**

Return `success` plus any error payload expected by the GUI.

- [ ] **Step 6: Verify tests and run a manual smoke test**

Run:
- `python -m pytest tests/test_adapter_dispatch.py -v`
- `python main_gui.py`

Check: PostgreSQL SQL export still generates the current file style; ClickHouse SQL export generates create + data statements.

- [ ] **Step 7: Commit**

```bash
git add core/exporter_db.py db/adapters/postgresql_adapter.py db/adapters/clickhouse_adapter.py gui/pages/database/exporter.py tests/test_adapter_dispatch.py
git commit -m "feat: add clickhouse sql export support"
```

### Task 7: Final verification and dependency/document touch-ups

**Files:**
- Modify: project dependency documentation if present (`README.md` or dependency file if added during implementation)

- [ ] **Step 1: Ensure `clickhouse-connect` is documented as a required dependency**

If the project already has a dependency manifest, add it there. If not, document install requirements in `README.md` or implementation notes.

- [ ] **Step 2: Run the full targeted verification set**

Run:
- `python -m pytest tests -v`
- `python -m compileall core db gui utils main_gui.py`
- `python main_gui.py`

Expected:
- tests pass
- compileall completes without syntax errors
- GUI launches and connection manager / import / export pages load

- [ ] **Step 3: Perform manual regression checks**

Verify:
- old connections without `db_type` still load as PostgreSQL
- PostgreSQL connection create/edit/export/import/sql-export still work
- ClickHouse connection create/edit/export/import/sql-export work
- connection list and selector still display connections correctly

- [ ] **Step 4: Commit**

```bash
git add README.md tests db core gui
git commit -m "chore: verify dual database support"
```
