# 数据迁移流式重构与通用分块设计

## 目标

重新设计数据迁移功能，满足：

1. **文件不落地**：默认流式传输，零磁盘 I/O；CSV 仅作兜底
2. **大表兼容**：PG→PG 真·COPY 管道；CK→CK 服务端 `remote()` 直传；异构路径 MemoryBudget 控内存
3. **断点续传**：按用户定义的分块任务持久化进度
4. **通用分块界面**：用户指定范围与切分方式，**不做 MIN/MAX 数据探测**（主键模式除外）
5. **DB 组合**：PG↔PG、CK↔CK、PG↔CK 全覆盖

## 非目标

- 数据库原生 FDW / Distributed 表配置（需 DBA 权限，不在本工具范围）
- 自动探测表数据 MIN/MAX 作为默认分块策略

---

## 架构概览

```
GUI（通用五步分块配置）
    ↓
MigrationOrchestrator（分块循环 + 断点 + 重试）
    ↓
split_strategy.compute_chunks(SplitConfig)  →  list[ChunkSpec]  （确定性生成，无数据探测）
    ↓
TransferPipeline.transfer_chunk()  →  按 (src_type, dst_type) 路由
    ├── PG→PG:  CopyBridge（COPY TO STDOUT → 有界缓冲 → COPY FROM STDIN）
    ├── CK→CK:  INSERT SELECT remote() / 物理 PARTITION（服务端直传）
    ├── PG↔CK:  stream_read + stream_write（MemoryBudget 控 batch）
    └── 降级:   export_csv + import_csv（临时磁盘）
```

### 双层粒度

| 层级 | 名称 | 持久化 | 说明 |
|------|------|--------|------|
| 外层 | Resume Chunk | 是（断点文件） | 用户配置的日历/分区/主键窗口 |
| 内层 | Transfer Batch | 否 | PG↔CK 异构路径的 fetchmany 批次；PG CopyBridge 字节缓冲 |

---

## 数据模型

### SplitMode / BindType

```python
class SplitMode(Enum):
    CALENDAR = "calendar"              # 日历切分（日/月/年）
    PARTITION_VALUE = "partition_value"  # 分区值列（yyyyMMdd 等）
    PHYSICAL_PARTITION = "physical"    # 物理分区（CH PART BY / PG 子表）
    KEY_RANGE = "key_range"            # 主键范围（高级，可选 MIN/MAX 探测）

class BindType(Enum):
    COLUMN = "column"
    EXPRESSION = "expression"
    NAME_TEMPLATE = "name_template"    # 物理分区名模板 orders_{yyyyMMdd}
    METADATA_LIST = "metadata_list"    # 从库读分区名列表（仅元数据）
```

### SplitConfig

```python
@dataclass
class SplitConfig:
    mode: SplitMode = SplitMode.PARTITION_VALUE

    # 范围（所有模式共用）
    range_start: str = ""
    range_end: str = ""
    value_format: Literal["yyyy-MM-dd", "yyyyMMdd", "yyyyMM", "yyyy"] = "yyyyMMdd"

    # 日历切分
    granularity: Literal["day", "month", "year"] = "day"

    # 绑定
    bind_type: BindType = BindType.COLUMN
    bind_target: str = ""              # 列名 / 表达式 / 模板 / 父表名

    # 每批数量（日历=单位数，分区=分区数）
    batch_size: int = 1

    # 附加业务过滤（与 chunk 范围 AND）
    extra_where: str = ""
```

### ChunkSpec（扩展）

```python
@dataclass
class ChunkSpec:
    chunk_index: int
    label: str                         # "20240601~20240607"
    where_sql: str = ""                # 逻辑过滤 WHERE 片段（不含 WHERE 关键字）
    physical_targets: list[str] = field(default_factory=list)  # 物理分区名
    key_start: Any = None              # KEY_RANGE 模式兼容
    key_end: Any = None
```

### MigrationCondition（演进）

保留 `table_name`、`target_table`、`enabled`、`mode`、`custom_sql`（SQL 模式）。

新增 `split: SplitConfig`；旧字段 `chunk_key`、`chunk_size`、`where_clause` 保留默认值以兼容旧配置 JSON（`where_clause` 映射到 `split.extra_where`）。

### MemoryBudgetConfig

```python
@dataclass
class MemoryBudgetConfig:
    limit_mb: int = 512
    sample_rows: int = 100
    min_batch_rows: int = 100
    max_batch_rows: int = 100_000
```

### TransferMode（保留）

```python
class TransferMode(Enum):
    CSV = "csv"
    STREAM = "stream"   # 默认
```

---

## 分块策略（无数据探测）

### 日历切分（CALENDAR）

输入：`range_start/end` + `granularity` + `batch_size` + `bind_target`

生成半开区间 `[start, end)` 的 chunk 列表，每块 `where_sql` 示例（PG）：

```sql
created_at >= '2024-06-01' AND created_at < '2024-06-08'
```

### 分区值切分（PARTITION_VALUE）

输入：`range_start=20240601`, `range_end=20240630`, `format=yyyyMMdd`, `batch_size=7`

```sql
p_date >= 20240601 AND p_date <= 20240607
```

表达式绑定：`toYYYYMMDD(event_time) BETWEEN 20240601 AND 20240607`（CK）

### 物理分区切分（PHYSICAL_PARTITION）

**模板模式**（不查库）：

```
模板 orders_{yyyyMMdd}, range 20240601~20240610, batch_size=3
→ Chunk0: [orders_20240601, orders_20240602, orders_20240603]
```

**元数据模式**（只读分区名，不扫数据）：

- CK: `SELECT DISTINCT partition FROM system.parts WHERE database=? AND table=?`
- PG: `pg_inherits` 查子表名

每 chunk 执行：

| 库 | SQL |
|----|-----|
| CK | `INSERT INTO dst SELECT * FROM src PARTITION '20240601'` |
| PG | `INSERT INTO dst SELECT * FROM ONLY child_table` |

### 主键范围（KEY_RANGE，高级）

保留现有 `probe_range` + int/datetime 切分，供向后兼容；非默认。

---

## 传输路径

### PG → PG（CopyBridge）

```
COPY (SELECT ... WHERE chunk) TO STDOUT
    → CopyBridge（ring buffer，≤ memory_limit × 25%）
    → COPY dst_table FROM STDIN
```

- 双线程：读 STDOUT 写 buffer；读 buffer 写 STDIN
- 禁止整块 StringIO 加载
- 首 chunk + truncate_before → TRUNCATE；续传永不 TRUNCATE

### CK → CK（服务端直传）

**Pull 模式**（默认，目标连源）：

```sql
INSERT INTO dst_table
SELECT ...
FROM remote('src_host:port', 'src_db', 'src_table', 'user', 'pass')
WHERE {chunk_where}
SETTINGS
    max_execution_time = 0,
    connect_timeout_with_failover_ms = 3000,
    receive_timeout = 3600,
    send_timeout = 3600
```

**Push 模式**（源连目标，网络隔离时 GUI 可选）：

```sql
INSERT INTO FUNCTION remoteSecure('dst_host:9440', 'db.table', 'user', 'pass')
SELECT ... FROM src_table WHERE {chunk_where}
```

物理分区：按 `physical_targets` 逐分区或合并执行。

客户端不传数据，不受客户端超时影响。

### PG ↔ CK（异构流式）

- PG 读：命名游标 `fetchmany`
- CK 读：**重写** `stream_read`，使用 `raw_stream` + Native/CSV 分块（禁止 `client.query()` 全量加载）
- 写：PG `execute_values`；CK `insert()` 批量
- MemoryBudget 动态计算 `batch_rows`

### CSV 降级

- 用户显式选择 CSV 模式
- 或开启「流式失败自动降级」（默认关闭）
- 仅 CSV 模式创建 `tempfile.mkdtemp`

---

## MemoryBudget 算法

每个 Resume Chunk 开始时（异构 / PG CopyBridge 缓冲 sizing）：

1. `SELECT * FROM ... WHERE chunk LIMIT sample_rows` 采样
2. `avg_row_bytes = total_bytes / sample_rows`
3. `batch_rows = clamp(limit_mb × 1024² × 0.5 / avg_row_bytes, min, max)`
4. CopyBridge buffer = `limit_mb × 0.25 × 1024²` 字节

CK→CK remote 路径不使用 MemoryBudget。

---

## GUI 设计

每张表卡片五步配置：

1. **迁移范围**：起始 / 结束 + 值格式
2. **切分方式**：日历 / 分区值 / 物理分区 / 主键（高级）
3. **数据绑定**：列名 / 表达式 / 模板 / 元数据列表
4. **每批数量** + **实时 chunk 预览**（纯 Python 生成，不发 SQL）
5. **附加过滤**（可选）

全局设置：

- 传输模式：流式（默认）/ CSV
- 内存上限 MB（默认 512）
- CK remote SETTINGS（可展开）
- 流式失败自动降级（默认关）

---

## 模块结构

```
src/core/migration/
  models.py              SplitConfig, ChunkSpec 扩展, MemoryBudgetConfig
  split_strategy.py        新增：calendar/partition/physical/key_range 生成
  memory_budget.py         新增
  copy_bridge.py             新增：PG CopyBridge
  transfer_pipeline.py       新增：统一传输路由
  orchestrator.py            简化，委托 Pipeline；STREAM 不建 temp_dir
  resume_manager.py          chunk label 持久化
  chunk_strategy.py          保留 KEY_RANGE 路径；或合并入 split_strategy

src/db/adapters/
  postgresql_adapter.py    CopyBridge 集成；废弃整块 StringIO copy_stream_transfer
  clickhouse_adapter.py      remote_transfer；重写 stream_read；stream_write 优化

src/gui/pages/database/
  migrator.py                通用五步分块 UI
```

---

## 错误处理

| 错误 | 处理 |
|------|------|
| 分块配置不完整（范围/绑定缺失） | validate 阶段拒绝 |
| 单 chunk 失败 | 重试 3 次（1s/2s/4s） |
| 重试耗尽 | 记录失败 chunk，继续后续 |
| CK remote 网络不通 | 尝试 Push；提示防火墙/IP 白名单 |
| 流式失败 | 可选降级 CSV |
| 断点损坏 | 警告，全新开始 |
| 物理分区元数据为空 | 报错，建议改模板模式 |

---

## 向后兼容

| 变更 | 策略 |
|------|------|
| 旧 JSON 无 `split` | 映射为 `KEY_RANGE` + 原 chunk_key/chunk_size/where_clause |
| `TransferMode` | 默认改为 STREAM（Orchestrator 与 GUI 一致） |
| `migrate_tables()` 签名 | 不变 |
| CSV 路径 | 保留 |

---

## 测试要点

- SplitConfig 四种 mode 的 chunk 生成（边界：单月、跨年、末块不足 batch_size）
- 物理分区模板 vs 元数据列表
- CopyBridge 大 chunk 内存不随 chunk 行数线性增长（mock COPY）
- CK remote SQL 构建（Pull/Push、SETTINGS）
- CK stream_read 不全量加载（mock raw_stream）
- Orchestrator STREAM 不创建 temp_dir；CSV 才创建
- 断点续传跳过已完成 chunk；续传不 TRUNCATE
- GUI chunk 预览与配置持久化
- 旧配置 JSON 向后兼容
