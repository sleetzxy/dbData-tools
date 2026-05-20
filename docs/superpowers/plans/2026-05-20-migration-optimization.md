# 数据迁移工具优化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 数据迁移工具支持目标表名独立配置、条件可选、流式管道传输（千亿级数据零磁盘 I/O）

**Architecture:** 新增 `TransferMode` 枚举控制传输路径（CSV/STREAM），`MigrationCondition` 增加 `target_table` 字段。STREAM 模式下 PG→PG 走 COPY 内存管道，异构走游标批次流转。Orchestrator 根据适配器类型自动选择最优路径。

**Tech Stack:** Python 3.10+, psycopg2, clickhouse-connect, pytest + pytest-mock

**Spec:** `docs/superpowers/specs/2026-05-20-migration-optimization-design.md`

---

### Task 1: 数据模型 — MigrationCondition.target_table + TransferMode 枚举

**Files:**
- Modify: `src/core/migration/models.py`

- [ ] **Step 1: 添加 TransferMode 枚举和 target_table 字段**

```python
from enum import Enum


class TransferMode(Enum):
    CSV = "csv"
    STREAM = "stream"


@dataclass
class MigrationCondition:
    table_name: str
    target_table: str = ""  # 新增：空=同源表名
    mode: Literal["where", "sql"]
    where_clause: str = ""
    custom_sql: str = ""
    chunk_key: str = ""
    chunk_size: int = 100_000
    enabled: bool = True
```

- [ ] **Step 2: 运行现有测试确认向后兼容**

Run: `pytest tests/test_migration_models.py -v`
Expected: 全部 PASS（新字段有默认值，不影响现有测试）

- [ ] **Step 3: Commit**

```bash
git add src/core/migration/models.py
git commit -m "feat(migration): 添加 TransferMode 枚举与 MigrationCondition.target_table 字段"
```

---

### Task 2: 适配器 — get_table_columns 方法

**Files:**
- Modify: `src/db/adapters/postgresql_adapter.py`
- Modify: `src/db/adapters/clickhouse_adapter.py`
- Create: `tests/test_adapter_table_columns.py`

- [ ] **Step 1: 写测试 — PG 适配器 get_table_columns**

```python
def test_pg_get_table_columns(mocker):
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    mock_cursor = mocker.MagicMock()
    mock_cursor.__iter__.return_value = iter([
        ("id",), ("name",), ("created_at",),
    ])
    mock_client = mocker.MagicMock()
    mock_client.cursor.return_value.__enter__.return_value = mock_cursor

    columns = adapter.get_table_columns(mock_client, "users", "public")
    assert columns == ["id", "name", "created_at"]
```

- [ ] **Step 2: 写测试 — CH 适配器 get_table_columns**

```python
def test_ch_get_table_columns(mocker):
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    mock_client = mocker.MagicMock()
    mock_client.query.return_value.result_columns = ["id", "name", "created_at"]

    columns = adapter.get_table_columns(mock_client, "users", "mydb")
    assert columns == ["id", "name", "created_at"]
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/test_adapter_table_columns.py -v`
Expected: FAIL（方法未定义）

- [ ] **Step 4: 实现 PG 适配器 get_table_columns**

```python
# PostgreSQLAdapter
def get_table_columns(
    self, client: psycopg2.extensions.connection, table: str, schema: str = "public",
) -> list[str]:
    table_str = str(table).strip()
    with client.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "ORDER BY ordinal_position",
            (schema, table_str),
        )
        return [row[0] for row in cursor]
```

- [ ] **Step 5: 实现 CH 适配器 get_table_columns**

```python
# ClickHouseAdapter
def get_table_columns(
    self, client: Any, table: str, database: str = "",
) -> list[str]:
    table_str = self._validate_identifier(table, "table")
    db_name = database or client.database
    result = client.query(
        f"SELECT name FROM system.columns "
        f"WHERE database = '{db_name}' AND table = '{table_str}' "
        f"ORDER BY position"
    )
    return list(result.result_columns) if result.result_columns else []
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_adapter_table_columns.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add src/db/adapters/postgresql_adapter.py src/db/adapters/clickhouse_adapter.py tests/test_adapter_table_columns.py
git commit -m "feat(adapters): 添加 get_table_columns 方法（PG + CH）"
```

---

### Task 3: 适配器 — stream_read 方法

**Files:**
- Modify: `src/db/adapters/postgresql_adapter.py`
- Modify: `src/db/adapters/clickhouse_adapter.py`
- Create: `tests/test_adapter_stream_read.py`

- [ ] **Step 1: 写测试 — PG stream_read 返回 (列名, 行批次生成器)**

```python
def test_pg_stream_read_yields_batches(mocker):
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    rows = [(1, "a"), (2, "b"), (3, "c")]
    mock_cursor = mocker.MagicMock()
    mock_cursor.description = [
        mocker.MagicMock(name="id"),
        mocker.MagicMock(name="name"),
    ]
    mock_cursor.fetchmany.side_effect = [rows[:2], rows[2:], []]
    mock_client = mocker.MagicMock()
    mock_client.cursor.return_value.__enter__.return_value = mock_cursor

    columns, batch_iter = adapter.stream_read(
        mock_client, "SELECT * FROM t", batch_size=2,
    )
    assert columns == ["id", "name"]
    batches = list(batch_iter)
    assert len(batches) == 2
    assert batches[0] == [(1, "a"), (2, "b")]
    assert batches[1] == [(3, "c")]
```

- [ ] **Step 2: 写测试 — CH stream_read**

```python
def test_ch_stream_read(mocker):
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    rows = [(1, "x"), (2, "y")]
    mock_client = mocker.MagicMock()
    mock_client.query.return_value.result_columns = ["id", "val"]
    mock_client.query.return_value.result_rows = rows

    columns, batch_iter = adapter.stream_read(
        mock_client, "SELECT * FROM t", batch_size=10000,
    )
    assert columns == ["id", "val"]
    batches = list(batch_iter)
    assert len(batches) == 1
    assert batches[0] == rows
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/test_adapter_stream_read.py -v`
Expected: FAIL

- [ ] **Step 4: 实现 PG stream_read**

PG 适配器使用命名游标（server-side cursor）+ fetchmany：

```python
def stream_read(
    self,
    client: psycopg2.extensions.connection,
    query: str,
    batch_size: int = 10000,
) -> tuple[list[str], Iterator[list[tuple]]]:
    cursor = client.cursor(name=f"stream_{id(self)}")
    cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]

    def _batches():
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield rows
        cursor.close()

    return columns, _batches()
```

- [ ] **Step 5: 实现 CH stream_read**

CH 的 clickhouse-connect 不支持服务端游标，一次性查询后按 batch_size 切片：

```python
def stream_read(
    self,
    client: Any,
    query: str,
    batch_size: int = 10000,
) -> tuple[list[str], Iterator[list[tuple]]]:
    result = client.query(query)
    columns = list(result.column_names)
    all_rows: list[tuple] = list(result.result_rows)

    def _batches():
        for i in range(0, len(all_rows), batch_size):
            yield all_rows[i:i + batch_size]

    return columns, _batches()
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_adapter_stream_read.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/db/adapters/postgresql_adapter.py src/db/adapters/clickhouse_adapter.py tests/test_adapter_stream_read.py
git commit -m "feat(adapters): 添加 stream_read 方法（PG 命名游标 + CH 批量读取）"
```

---

### Task 4: 适配器 — stream_write 方法

**Files:**
- Modify: `src/db/adapters/postgresql_adapter.py`
- Modify: `src/db/adapters/clickhouse_adapter.py`
- Create: `tests/test_adapter_stream_write.py`

- [ ] **Step 1: 写测试 — PG stream_write 使用 execute_values**

```python
def test_pg_stream_write(mocker):
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    mock_cursor = mocker.MagicMock()
    mock_client = mocker.MagicMock()
    mock_client.cursor.return_value.__enter__.return_value = mock_cursor

    rows_batch1 = [(1, "a"), (2, "b")]
    rows_batch2 = [(3, "c")]
    def batch_iter():
        yield rows_batch1
        yield rows_batch2

    count = adapter.stream_write(
        mock_client, "users", ["id", "name"], batch_iter(), "public",
    )
    assert count == 3
```

- [ ] **Step 2: 写测试 — CH stream_write 使用批量 INSERT VALUES**

```python
def test_ch_stream_write(mocker):
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    mock_client = mocker.MagicMock()

    def batch_iter():
        yield [(1, "x"), (2, "y")]
        yield [(3, "z")]

    count = adapter.stream_write(
        mock_client, "users", ["id", "val"], batch_iter(), "mydb",
    )
    assert count == 3
    assert mock_client.command.call_count == 2
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/test_adapter_stream_write.py -v`
Expected: FAIL

- [ ] **Step 4: 实现 PG stream_write**

```python
def stream_write(
    self,
    client: psycopg2.extensions.connection,
    table: str,
    columns: list[str],
    rows_iter: Iterator[list[tuple]],
    schema: str = "public",
) -> int:
    from psycopg2.extras import execute_values

    total = 0
    cols_sql = sql.SQL(", ").join(
        sql.Identifier(c) for c in columns
    )
    insert_sql = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s").format(
        sql.Identifier(schema), sql.Identifier(table), cols_sql,
    )
    with client.cursor() as cursor:
        for batch in rows_iter:
            execute_values(cursor, insert_sql, batch)
            total += len(batch)
    client.commit()
    return total
```

- [ ] **Step 5: 实现 CH stream_write**

```python
def stream_write(
    self,
    client: Any,
    table: str,
    columns: list[str],
    rows_iter: Iterator[list[tuple]],
    database: str = "",
) -> int:
    total = 0
    db_name = database or client.database
    full_table = self._qualified_table(db_name, table)
    col_str = ", ".join(self._quote_identifier(c) for c in columns)
    for batch in rows_iter:
        if not batch:
            continue
        placeholders = ", ".join(["%s"] * len(columns))
        values = ", ".join(
            f"({placeholders})" for _ in batch
        )
        flat_values = [v for row in batch for v in row]
        client.command(
            f"INSERT INTO {full_table} ({col_str}) VALUES {values}",
            flat_values,
        )
        total += len(batch)
    return total
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_adapter_stream_write.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/db/adapters/postgresql_adapter.py src/db/adapters/clickhouse_adapter.py tests/test_adapter_stream_write.py
git commit -m "feat(adapters): 添加 stream_write 方法（PG execute_values + CH INSERT VALUES）"
```

---

### Task 5: 适配器 — PG copy_stream_transfer 方法

**Files:**
- Modify: `src/db/adapters/postgresql_adapter.py`
- Create: `tests/test_adapter_copy_stream.py`

- [ ] **Step 1: 写测试**

```python
def test_copy_stream_transfer(mocker):
    from db.adapters.postgresql_adapter import PostgreSQLAdapter
    import io

    adapter = PostgreSQLAdapter()

    mock_src_cursor = mocker.MagicMock()
    mock_dst_cursor = mocker.MagicMock()
    mock_src_client = mocker.MagicMock()
    mock_dst_client = mocker.MagicMock()
    mock_src_client.cursor.return_value.__enter__.return_value = mock_src_cursor
    mock_dst_client.cursor.return_value.__enter__.return_value = mock_dst_cursor

    # Mock src COPY to write data to buffer
    def copy_to_stdout(sql_str, buf):
        buf.write("1,a\n2,b\n3,c\n")
    mock_src_cursor.copy_expert.side_effect = copy_to_stdout

    count = adapter.copy_stream_transfer(
        mock_src_client, mock_dst_client,
        "SELECT * FROM users WHERE id >= 1 AND id < 100",
        "users", ["id", "name"], "public",
    )
    # 3 rows (header is not included in content since format CSV header is false)
    assert count == 3
    mock_dst_cursor.copy_expert.assert_called_once()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_adapter_copy_stream.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 copy_stream_transfer**

```python
def copy_stream_transfer(
    self,
    src_client: psycopg2.extensions.connection,
    dst_client: psycopg2.extensions.connection,
    src_query: str,
    dst_table: str,
    columns: list[str],
    schema: str = "public",
) -> int:
    import io
    from psycopg2 import sql as psql

    buffer = io.StringIO()

    with src_client.cursor() as src_cur:
        copy_out = psql.SQL("COPY ({}) TO STDOUT WITH (FORMAT CSV, HEADER false)").format(
            psql.SQL(src_query)
        )
        src_cur.copy_expert(copy_out.as_string(src_client), buffer)

    buffer.seek(0)
    content = buffer.getvalue()
    if not content.strip():
        return 0
    row_count = content.count("\n")

    with dst_client.cursor() as dst_cur:
        cols_sql = psql.SQL(", ").join(psql.Identifier(c) for c in columns)
        copy_in = psql.SQL("COPY {}.{} ({}) FROM STDIN WITH (FORMAT CSV)").format(
            psql.Identifier(schema),
            psql.Identifier(dst_table),
            cols_sql,
        )
        dst_cur.copy_expert(copy_in.as_string(dst_client), buffer)

    dst_client.commit()
    return row_count
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_adapter_copy_stream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db/adapters/postgresql_adapter.py tests/test_adapter_copy_stream.py
git commit -m "feat(adapters): 添加 copy_stream_transfer（PG→PG COPY 内存管道）"
```

---

### Task 6: Orchestrator — 流式传输路径

**前置验证:** 确认两个适配器的 `_build_chunked_query` 签名接受 `chunk_start`/`chunk_end` 参数 —
已在第三步设计探索中确认 PG (`postgresql_adapter.py:291`) 和 CH (`clickhouse_adapter.py:125`)
均支持 `chunk_start: Any = None, chunk_end: Any = None`。

**Files:**
- Modify: `src/core/migration/orchestrator.py`
- Create: `tests/test_orchestrator_stream.py`

- [ ] **Step 1: 写测试 — STREAM 模式 PG→PG 单分块迁移**

```python
def test_orchestrator_stream_mode_pg_to_pg(mocker):
    from core.migration.models import MigrationCondition, TransferMode
    from core.migration.orchestrator import MigrationOrchestrator

    mock_src_adapter = mocker.MagicMock()
    mock_src_adapter.db_type = "postgresql"
    mock_src_adapter.create_client.return_value = mocker.MagicMock()
    mock_dst_adapter = mocker.MagicMock()
    mock_dst_adapter.db_type = "postgresql"
    mock_dst_adapter.create_client.return_value = mocker.MagicMock()

    # mock chunk strategy
    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=[mocker.MagicMock(chunk_index=0, key_start=1, key_end=100)],
    )
    mocker.patch(
        "core.migration.orchestrator.detect_chunk_key",
        return_value="id",
    )

    mock_src_adapter.copy_stream_transfer.return_value = 50000
    mock_src_adapter._build_chunked_query.return_value = "SELECT ..."

    cond = MigrationCondition(table_name="users", mode="where")
    orch = MigrationOrchestrator(
        src_config={"db_type": "postgresql"},
        dst_config={"db_type": "postgresql"},
        conditions=[cond],
        src_adapter=mock_src_adapter,
        dst_adapter=mock_dst_adapter,
        transfer_mode=TransferMode.STREAM,
    )
    orch._can_use_copy_pipe = mocker.MagicMock(return_value=True)

    result = orch.run()
    assert result["success"] is True
    mock_src_adapter.copy_stream_transfer.assert_called_once()
```

- [ ] **Step 2: 写测试 — STREAM 模式异构路径（PG→CH）**

```python
def test_orchestrator_stream_mode_heterogeneous(mocker):
    from core.migration.models import MigrationCondition, TransferMode
    from core.migration.orchestrator import MigrationOrchestrator

    mock_src_adapter = mocker.MagicMock()
    mock_src_adapter.db_type = "postgresql"
    mock_src_adapter.create_client.return_value = mocker.MagicMock()
    mock_dst_adapter = mocker.MagicMock()
    mock_dst_adapter.db_type = "clickhouse"
    mock_dst_adapter.create_client.return_value = mocker.MagicMock()

    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=[mocker.MagicMock(chunk_index=0, key_start=1, key_end=100)],
    )
    mocker.patch(
        "core.migration.orchestrator.detect_chunk_key",
        return_value="id",
    )

    mock_src_adapter._build_chunked_query.return_value = "SELECT ..."
    mock_src_adapter.stream_read.return_value = (
        ["id", "name"],
        iter([[(1, "a"), (2, "b")]]),
    )
    mock_dst_adapter.stream_write.return_value = 2

    cond = MigrationCondition(table_name="users", mode="where")
    orch = MigrationOrchestrator(
        src_config={"db_type": "postgresql"},
        dst_config={"db_type": "clickhouse"},
        conditions=[cond],
        src_adapter=mock_src_adapter,
        dst_adapter=mock_dst_adapter,
        transfer_mode=TransferMode.STREAM,
    )

    result = orch.run()
    assert result["success"] is True
    mock_src_adapter.stream_read.assert_called_once()
    mock_dst_adapter.stream_write.assert_called_once()
```

- [ ] **Step 3: 写测试 — STREAM 模式目标表名映射**

```python
def test_orchestrator_target_table_mapping(mocker):
    from core.migration.models import MigrationCondition, TransferMode
    from core.migration.orchestrator import MigrationOrchestrator

    mock_src_adapter = mocker.MagicMock()
    mock_src_adapter.db_type = "postgresql"
    mock_src_adapter.create_client.return_value = mocker.MagicMock()
    mock_dst_adapter = mocker.MagicMock()
    mock_dst_adapter.db_type = "postgresql"
    mock_dst_adapter.create_client.return_value = mocker.MagicMock()

    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=[mocker.MagicMock(chunk_index=0, key_start=1, key_end=100)],
    )
    mocker.patch("core.migration.orchestrator.detect_chunk_key", return_value="id")
    mock_src_adapter._build_chunked_query.return_value = "SELECT ..."
    mock_src_adapter.copy_stream_transfer.return_value = 100

    cond = MigrationCondition(
        table_name="source_users", target_table="target_users", mode="where",
    )
    orch = MigrationOrchestrator(
        src_config={"db_type": "postgresql"},
        dst_config={"db_type": "postgresql"},
        conditions=[cond],
        src_adapter=mock_src_adapter,
        dst_adapter=mock_dst_adapter,
        transfer_mode=TransferMode.STREAM,
    )
    orch._can_use_copy_pipe = mocker.MagicMock(return_value=True)

    result = orch.run()
    assert result["success"] is True
    # 确认目标表名使用了 target_table
    call_kwargs = mock_src_adapter.copy_stream_transfer.call_args
    assert call_kwargs[0][3] == "target_users"
```

- [ ] **Step 4: 运行测试确认失败**

Run: `pytest tests/test_orchestrator_stream.py -v`
Expected: FAIL（orchestrator 还不支持 transfer_mode / _stream_chunk）

- [ ] **Step 5: 实现 Orchestrator 流式路径**

修改 `src/core/migration/orchestrator.py`：

**5a. 新增导入与构造函数参数：**

```python
from core.migration.models import TransferMode

class MigrationOrchestrator:
    def __init__(
        self, ...,
        transfer_mode: TransferMode = TransferMode.STREAM,  # 默认流式
        stream_batch_size: int = 10000,
    ):
        ...
        self.transfer_mode = transfer_mode
        self.stream_batch_size = stream_batch_size
```

**5b. 修改 `_migrate_table` 块处理循环：**

在现有分块循环中，将导出+导入逻辑替换为根据 transfer_mode 选择路径：

```python
# 在 _migrate_table 的 retry loop 中：
if self.transfer_mode == TransferMode.STREAM:
    target = cond.target_table or cond.table_name
    rows_in_chunk = self._stream_chunk(
        cond=cond,
        src_client=src_client,
        dst_client=dst_client,
        chunk=chunk,
        target_table=target,
    )
else:
    csv_path, rows_in_chunk = self._export_chunk(...)
    is_first = chunk_index == 0
    self._import_chunk(...)
```

注意：CSV 路径的 `_import_chunk` 也需支持 target_table（当前硬编码使用 `cond.table_name`）。添加：

```python
def _import_chunk(self, cond, dst_client, csv_path, is_first_chunk):
    target_table = cond.target_table or cond.table_name
    ...
    result = self.dst_adapter.import_csv(
        ...,
        table_names=[target_table],  # 使用映射后的目标表名
        ...
    )
```

**5c. 新增 `_stream_chunk` 方法：**

```python
def _stream_chunk(
    self,
    cond: MigrationCondition,
    src_client: Any,
    dst_client: Any,
    chunk: ChunkSpec,
    target_table: str,
) -> int:
    chunk_key = cond.chunk_key
    if not chunk_key:
        chunk_key = detect_chunk_key(
            self.src_adapter, src_client, cond.table_name, self.src_schema,
        )

    # 透传 chunk 参数给 _build_chunked_query
    src_query = self.src_adapter._build_chunked_query(
        table=cond.table_name,
        schema=self.src_schema,
        where_clause=cond.where_clause,
        custom_sql=cond.custom_sql,
        chunk_key=chunk_key,
        chunk_start=chunk.key_start,
        chunk_end=chunk.key_end,
    )

    if self._can_use_copy_pipe():
        columns = self.dst_adapter.get_table_columns(
            dst_client, target_table, self.dst_schema,
        )
        return self.src_adapter.copy_stream_transfer(
            src_client, dst_client,
            src_query.as_string(src_client)
            if hasattr(src_query, "as_string")
            else str(src_query),
            target_table, columns, self.dst_schema,
        )
    else:
        query_str = (
            src_query.as_string(src_client)
            if hasattr(src_query, "as_string")
            else str(src_query)
        )
        col_names, rows_iter = self.src_adapter.stream_read(
            src_client, query_str, self.stream_batch_size,
        )
        return self.dst_adapter.stream_write(
            dst_client, target_table, col_names, rows_iter, self.dst_schema,
        )

def _can_use_copy_pipe(self) -> bool:
    return (
        self.src_adapter.db_type == "postgresql"
        and self.dst_adapter.db_type == "postgresql"
        and hasattr(self.src_adapter, "copy_stream_transfer")
    )
```

**5d. 修改 `_export_chunk` 和 `_import_chunk` 中的表名引用：**

`_export_chunk` — 源表保持使用 `cond.table_name`（从源库读取）。
`_import_chunk` — 目标表使用 `cond.target_table or cond.table_name`。

- [ ] **Step 6: 运行新测试确认通过**

Run: `pytest tests/test_orchestrator_stream.py -v`
Expected: PASS

- [ ] **Step 7: 运行全部现有测试确认无回归**

Run: `pytest tests/test_orchestrator.py tests/test_migrator.py -v`
Expected: 全部 PASS（默认 CSV 模式行为不变）

- [ ] **Step 8: Commit**

```bash
git add src/core/migration/orchestrator.py tests/test_orchestrator_stream.py
git commit -m "feat(orchestrator): 添加 STREAM 传输模式与 target_table 支持"
```

---

### Task 7: migrator 入口 — 传递 transfer_mode

**Files:**
- Modify: `src/core/migrator.py`
- Modify: `tests/test_migrator.py`

- [ ] **Step 1: 修改 migrate_tables 支持 transfer_mode**

```python
from core.migration.models import TransferMode

def migrate_tables(
    src_config, dst_config, table_names,
    truncate_before=True,
    src_adapter=None, dst_adapter=None,
    logger=None, conditions=None,
    transfer_mode: TransferMode = TransferMode.CSV,  # 入口默认 CSV 保持向后兼容
    stream_batch_size: int = 10000,  # 新增
) -> dict:
    ...
    orchestrator = MigrationOrchestrator(
        ...,
        transfer_mode=transfer_mode,
        stream_batch_size=stream_batch_size,
    )
```

> 说明：Orchestrator 内部默认 STREAM，但 `migrate_tables()` 入口保持 CSV 默认，
> 保证现有的直接调用方（如测试）行为不变。GUI 层显式传 STREAM。
```

- [ ] **Step 2: 运行测试确认无回归**

Run: `pytest tests/test_migrator.py -v`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add src/core/migrator.py
git commit -m "feat(migrator): 入口支持 transfer_mode 与 stream_batch_size 参数"
```

---

### Task 8: GUI — _TableCard 增加目标表名

**Files:**
- Modify: `src/gui/pages/database/migrator.py`

- [ ] **Step 1: 修改 _TableCard 头部布局，增加目标表名输入**

在 `_TableCard.__init__` 中，header frame 内增加目标表名 Entry：

```python
# 表名输入（源表）
self.name_var = tk.StringVar(value=table_name)
self.name_entry = ctk.CTkEntry(
    self.header,
    textvariable=self.name_var,
    placeholder_text=f"源表名 #{index + 1}",
    font=("Microsoft YaHei", 11),
    height=30,
    fg_color=colors["bg"],
    border_color=colors["border"],
)
self.name_entry.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=4)

# 目标表名输入（新增）
self.target_var = tk.StringVar()
self.target_entry = ctk.CTkEntry(
    self.header,
    textvariable=self.target_var,
    placeholder_text="目标表名（空=同源）",
    font=("Microsoft YaHei", 11),
    height=30,
    width=140,
    fg_color=colors["bg"],
    border_color=colors["border"],
)
self.target_entry.pack(side="left", padx=(0, 4), pady=4)
```

- [ ] **Step 2: 修改 _TableCard.to_condition() 包含 target_table**

```python
def to_condition(self) -> MigrationCondition | None:
    name = self.name_var.get().strip()
    if not name or not self._TABLE_NAME_RE.match(name):
        return None
    return MigrationCondition(
        table_name=name,
        target_table=self.target_var.get().strip(),  # 新增
        ...
    )
```

- [ ] **Step 3: 修改 _TableCard.configure() 回填 target_table**

```python
def configure(self, cond: MigrationCondition) -> None:
    self.name_var.set(cond.table_name)
    self.target_var.set(cond.target_table)  # 新增
    ...
```

- [ ] **Step 4: 修改条件标签为可选**

将 `"WHERE 子句（不含 WHERE 关键字）"` 改为 `"WHERE 子句（可选）"`。

- [ ] **Step 5: 修改验证逻辑 — 空条件允许通过**

在 `MigratorPage.validate()` 中，移除对 SQL 模式空内容的强制校验。但保留 SQL 模式下 chunk_key 必填的检查（分块仍需键）。

- [ ] **Step 6: 修改配置持久化 get_config_dict/apply_config 包含 target_table**

在 `get_config_dict()` 中为每个 table_config 增加 `"target_table": c.target_var.get().strip()`。
在 `apply_config()` 中读取并设置 `card.target_var.set(tc.get("target_table", ""))`。

- [ ] **Step 7: Commit**

```bash
git add src/gui/pages/database/migrator.py
git commit -m "feat(gui): _TableCard 增加目标表名输入，条件改为可选"
```

---

### Task 9: GUI — 传输模式切换与默认流式

**Files:**
- Modify: `src/gui/pages/database/migrator.py`

- [ ] **Step 1: 在全局设置区增加传输模式单选框**

在 `setup_left_panel_content` 的 settings_frame 中，TRUNCATE 下方新增：

```python
# 传输模式
mode_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
mode_row.pack(fill="x", padx=10, pady=(4, 8))
StyledLabel(mode_row, text="传输模式").pack(side="left", padx=(0, 8))
self.transfer_mode_var = tk.StringVar(value="stream")
ctk.CTkRadioButton(
    mode_row, text="流式", variable=self.transfer_mode_var, value="stream",
    font=("Microsoft YaHei", 10),
    text_color=self.idea_dark_colors["text_primary"],
    fg_color=self.idea_dark_colors["accent"],
    hover_color=self.idea_dark_colors["accent_hover"],
    border_color=self.idea_dark_colors["border"],
).pack(side="left", padx=(0, 8))
ctk.CTkRadioButton(
    mode_row, text="CSV", variable=self.transfer_mode_var, value="csv",
    font=("Microsoft YaHei", 10),
    text_color=self.idea_dark_colors["text_primary"],
    fg_color=self.idea_dark_colors["accent"],
    hover_color=self.idea_dark_colors["accent_hover"],
    border_color=self.idea_dark_colors["border"],
).pack(side="left")
```

- [ ] **Step 2: 修改 execute_task 传递 transfer_mode**

```python
from core.migration.models import TransferMode

def execute_task(self):
    ...
    mode = TransferMode.STREAM if self.transfer_mode_var.get() == "stream" else TransferMode.CSV
    result = migrate_tables(
        ...,
        transfer_mode=mode,
    )
```

- [ ] **Step 3: 修改配置持久化包含 transfer_mode**

`get_config_dict` 增加 `"transfer_mode": self.transfer_mode_var.get()`。
`apply_config` 增加 `self.transfer_mode_var.set(config.get("transfer_mode", "stream"))`。

- [ ] **Step 4: Commit**

```bash
git add src/gui/pages/database/migrator.py
git commit -m "feat(gui): 添加传输模式切换（流式/CSV）默认流式"
```

---

### Task 10: 集成验证

**Files:**
- 无新增，回归验证

- [ ] **Step 1: 运行完整测试套件**

Run: `pytest -v`
Expected: 全部 PASS

- [ ] **Step 2: 编译检查**

Run: `python -m compileall src/core src/db src/gui src/utils main_gui.py`
Expected: 无语法错误

- [ ] **Step 3: 启动 GUI 手工验证**

Run: `python main_gui.py`

验证步骤：
1. 进入"数据迁移"页面
2. 确认左侧面板新增"目标表名"输入框和"传输模式"单选框
3. 配置源和目标连接
4. 添加一张表，只填源表名和目标表名，不填条件
5. 确认"WHERE 子句（可选）"标签已更新
6. 切换传输模式（流式/CSV）
7. 关闭应用
8. 重新打开 → 确认配置已持久化

- [ ] **Step 4: Commit（如有调整）**

```bash
git add -A
git commit -m "chore: 集成验证修复"
```

---

### Task 11: 最终审查与清理

- [ ] **Step 1: 运行所有测试确认通过**

Run: `pytest -v`
Expected: 全部 PASS

- [ ] **Step 2: 运行覆盖率检查**

Run: `pytest --cov=core.migration --cov=db.adapters --cov=gui.pages.database --cov-report=term-missing`
Expected: 新增代码被测试覆盖

- [ ] **Step 3: 最终 commit**

```bash
git add -A
git commit -m "chore: 最终审查与清理"
```
