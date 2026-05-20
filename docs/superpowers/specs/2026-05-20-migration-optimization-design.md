# 数据迁移工具优化

## 目标

在现有数据迁移功能基础上进行三项优化：

1. **目标表名可配置**：输入表与输出表独立指定，不再强制同名
2. **条件真正可选**：WHERE 条件/SQL 均为可选，支持全表迁移
3. **超大表流式传输**：千亿级数据通过内存管道直传，消除磁盘 I/O 瓶颈

---

## 数据模型变更

### MigrationCondition — 新增 target_table 字段

```python
@dataclass
class MigrationCondition:
    table_name: str                          # 源表名
    target_table: str = ""                   # 目标表名（空=与源表同名，向后兼容）
    mode: Literal["where", "sql"]            # 模式
    where_clause: str = ""                   # WHERE 子句（可选）
    custom_sql: str = ""                     # 自定义 SQL（可选）
    chunk_key: str = ""                      # 分块键，空=自动检测
    chunk_size: int = 100_000                # 每块行数
    enabled: bool = True                     # 是否参与本次迁移
```

向后兼容性：`target_table` 为空时所有调用退化为使用 `table_name`。

### TransferMode — 新增传输模式枚举

```python
class TransferMode(Enum):
    CSV = "csv"          # 磁盘文件中转（现有模式，保留）
    STREAM = "stream"    # 内存管道直传（新增，推荐用于大表）
```

---

## 流式管道架构

### 数据流对比

```
CSV 模式（现有）：
  源库 → COPY TO STDOUT → 磁盘 CSV 文件 → COPY FROM STDIN → 目标库
  瓶颈：磁盘写入 + 磁盘读取，每个分块两次 I/O

STREAM 模式（新增）：
  源库 → COPY TO STDOUT → io.StringIO 内存缓冲 → COPY FROM STDIN → 目标库
  瓶颈消除：数据仅在内存中流转，零磁盘 I/O
```

### 同构流式（PG→PG）

```
┌──────────┐    COPY (SELECT...)     ┌──────────────┐    COPY FROM STDIN    ┌──────────┐
│ 源 PG    │ ──────────────────────→ │ io.StringIO  │ ───────────────────→ │ 目标 PG  │
│          │    TO STDOUT (CSV)      │  (内存缓冲)   │    WITH (FORMAT CSV) │          │
└──────────┘                         └──────────────┘                      └──────────┘
```

- 利用 PostgreSQL 的 COPY 二进制 CSV 协议，无需逐行解析
- 每次只缓冲一个分块的数据（通常 10-50MB），内存可控
- 使用 `cursor.copy_expert()` 两端对接

### 异构流式（PG↔CH）

```
┌──────────┐    SELECT + 服务端游标    ┌──────────────┐    INSERT VALUES 批量    ┌──────────┐
│ 源库     │ ─────────────────────→   │ Python 生成器 │ ────────────────────→  │ 目标库   │
│          │    fetchmany(batch)       │  (批次迭代)   │    executemany         │          │
└──────────┘                           └──────────────┘                        └──────────┘
```

- 源端使用服务端游标（`WITH HOLD CURSOR`），避免大数据量 OOM
- 每批 `fetchmany(10000)` 行，流式传递给目标端
- 目标端使用批量 INSERT（`INSERT INTO ... VALUES (...), (...), ...`）
- PG→CH 时处理 Python 类型到 ClickHouse 类型的转换

### 自动路径选择

Orchestrator 在 `_stream_chunk()` 中根据适配器类型自动选择：

| 源 | 目标 | 路径 |
|---|------|------|
| PG | PG | COPY → StringIO → COPY |
| PG | CH | SELECT cursor → fetchmany → INSERT VALUES |
| CH | PG | SELECT cursor → fetchmany → INSERT VALUES |
| CH | CH | SELECT cursor → fetchmany → INSERT VALUES |

---

## 适配器接口变更

### 已有方法说明

`_build_chunked_query()` 已在两个适配器中实现（私有方法），用于根据条件/分块键/范围拼装 SELECT
查询。流式路径复用该方法构造查询 SQL，然后传给 `stream_read()` 或 `copy_stream_transfer()`。

### 协议新增方法

```python
class AdapterProtocol(Protocol):
    # 现有方法保持不变
    def export_csv(...) -> dict: ...
    def import_csv(...) -> dict: ...

    # 新增：流式读取
    def stream_read(
        self, client, query: str, batch_size: int = 10000
    ) -> tuple[list[str], Iterator[list[tuple]]]:
        """执行查询，返回 (列名列表, 行批次生成器)。

        生成器每次 yield 一个 list[tuple]（一批行），调用方逐批消费后
        传给 stream_write()。列名在调用时立即获取，不参与迭代。
        """
        ...

    # 新增：流式写入
    def stream_write(
        self, client, table: str, columns: list[str],
        rows_iter: Iterator[list[tuple]], schema: str = "",
    ) -> int:
        """消费行批次生成器，写入目标表，返回总行数。"""
        ...

    # 新增：COPY 管道传输（仅 PG 适配器实现）
    def copy_stream_transfer(
        self, src_client, dst_client, src_query: str,
        dst_table: str, columns: list[str], schema: str = "",
    ) -> int:
        """PG→PG 高速通道：COPY TO STDOUT → 内存 → COPY FROM STDIN。"""
        ...
```

### PostgreSQL 适配器

- `copy_stream_transfer()`: 将 `src_query` 的 COPY 输出写入 `io.StringIO`，再通过 COPY FROM STDIN 写入目标表
- `stream_read()`: 使用命名游标 + `fetchmany`，执行查询后立即获取 `cursor.description` 得到列名
- `stream_write()`: 使用 `execute_values()` 批量写入

### ClickHouse 适配器

- `stream_read()`: 使用 CH 客户端 cursor + `fetchmany`，从 `cursor.description` 获取列名
- `stream_write()`: 使用 `INSERT INTO ... VALUES` 批量语法
- 无 `copy_stream_transfer()`（CH 不支持 COPY 协议）

---

## Orchestrator 变更

### 新增参数

```python
class MigrationOrchestrator:
    def __init__(
        self, ...,
        transfer_mode: TransferMode = TransferMode.STREAM,  # 默认使用流式
        stream_batch_size: int = 10000,  # 流式批次大小
    ):
```

### _migrate_table 流程调整

```
_migrate_table(cond):
    target = cond.target_table or cond.table_name   ← 解析目标表名

    for chunk in chunks:
        if transfer_mode == STREAM:
            rows = _stream_chunk(cond, chunk, target)   ← 新增流式路径
        else:
            csv_path, rows = _export_chunk(...)         ← 现有 CSV 路径
            _import_chunk(...)

    # 其余重试/断点/进度逻辑不变
```

### _stream_chunk 实现

```python
def _stream_chunk(self, cond, src_client, dst_client, chunk, target_table):
    query = self.src_adapter._build_chunked_query(...)

    # 从目标表获取列信息（COPY 和 INSERT 都需要）
    columns = self.dst_adapter.get_table_columns(dst_client, target_table, self.dst_schema)

    if self._can_use_copy_pipe():
        # PG→PG 高速通道
        return self.src_adapter.copy_stream_transfer(
            src_client, dst_client, query, target_table, columns, self.dst_schema,
        )
    else:
        # 异构路径：stream_read 返回 (columns, rows_iter)
        col_names, rows_iter = self.src_adapter.stream_read(
            src_client, query, self.batch_size
        )
        return self.dst_adapter.stream_write(
            dst_client, target_table, col_names, rows_iter, self.dst_schema,
        )
```

`_can_use_copy_pipe()` 在源和目标适配器均为 PostgreSQL 时返回 True，
即 `src_adapter.db_type == "postgresql" and dst_adapter.db_type == "postgresql"`。

---

## GUI 变更

### _TableCard 卡片增加目标表输入

```
┌────────────────────────────────────────────┐
│ [源表名________] [目标表名________] [▸] [×] │  ← 折叠头部增加目标表名
├────────────────────────────────────────────┤
│  模式: ○ 条件  ○ 自定义 SQL                │
│  WHERE 子句（可选）: [___________________]  │  ← 标签加"可选"
│  分块键: [________]  块行数: [______]      │
└────────────────────────────────────────────┘
```

- 目标表名输入框（可选，placeholder="同源表名"）
- 条件标签从 `"WHERE 子句（不含 WHERE 关键字）"` 改为 `"WHERE 子句（可选）"`

### MigratorPage 增加传输模式选择

在全局设置区增加：
- `transfer_mode` 单选框：`CSV 文件` / `流式传输`（默认流式）

### 配置持久化

`get_config_dict()` / `apply_config()` 增加 `target_table` 和 `transfer_mode` 字段的读写。

---

## 测试策略

### 模型层
- `MigrationCondition` 新增 `target_table` 字段的构造与默认值测试
- `TransferMode` 枚举值测试

### 流式传输
- PG→PG `copy_stream_transfer` 正确性测试（mock cursor）
- PG→CH `stream_read` + `stream_write` 端到端测试
- 空表、单行、多批次覆盖
- 异常路径：传输中断、列不匹配

### Orchestrator
- STREAM 模式下的单表/多表迁移
- CSV 模式回归（不破坏现有行为）
- `target_table` 为空时退化为 `table_name`
- `target_table` 非空时正确路由

### GUI
- 目标表名输入展示与回填
- 配置持久化含新字段
- 传输模式切换

---

## 向后兼容性

| 变更 | 兼容策略 |
|------|---------|
| `target_table` 新字段 | 默认值 `""`，所有现有调用无需修改 |
| `TransferMode` 枚举 | Orchestrator 默认 `STREAM`，migrator.py 入口保持 CSV 默认 |
| 适配器新方法 | 独立新增，不影响现有 `export_csv`/`import_csv` |
| GUI 新字段 | 配置 JSON 新增 key，旧配置缺失时使用默认值 |

---

## 风险与约束

- **流式 COPY 管道仅限 PG→PG**：异构场景使用批量 INSERT，速度慢于 COPY 但仍无磁盘 I/O
- **内存控制**：流式模式每个分块数据全在内存，默认分块大小 100K 行通常占用 10-50MB。分块大小过大时可能 OOM
- **断点续传兼容**：切换传输模式不影断点恢复，断点记录的是已完成的分块编号
