# 数据迁移功能重新设计

## 目标

重新设计数据迁移功能，支持：
1. **条件迁移**：WHERE 过滤 + 自定义 SQL 双模
2. **千亿级数据表迁移**：主键/时间分块，分块级重试，断点可恢复

## 数据模型

### MigrationCondition — 单表迁移配置

```python
@dataclass
class MigrationCondition:
    table_name: str                          # 表名
    mode: Literal["where", "sql"]            # 模式
    where_clause: str = ""                   # 条件模式：WHERE 子句（不含 WHERE 关键字）
    custom_sql: str = ""                     # SQL 模式：完整 SELECT
    chunk_key: str = ""                      # 分块键（列名），空=自动检测
    chunk_size: int = 100_000                # 每块行数
    enabled: bool = True                     # 是否参与本次迁移
```

### ChunkSpec — 单个分块描述

```python
@dataclass
class ChunkSpec:
    chunk_index: int                         # 分块序号（从 0 开始）
    key_start: Any                           # 切分键起始值（None 表示无下界）
    key_end: Any                             # 切分键结束值（None 表示无上界）
```

### TableMigrationResult — 单表迁移结果

```python
@dataclass
class TableMigrationResult:
    table_name: str
    success: bool
    total_rows: int
    total_chunks: int
    completed_chunks: int
    error: str = ""
```

### ChunkProgress — 进度回调数据

```python
@dataclass
class ChunkProgress:
    table_name: str
    chunk_index: int
    total_table_chunks: int
    total_across_all_tables: int
    completed_across_all_tables: int
    rows: int
```

### MigrationMeta — 迁移元数据（断点文件持久化）

```python
@dataclass
class MigrationMeta:
    migration_id: str                        # UUID
    tables: list[MigrationCondition]         # 表配置列表
    completed_chunks: dict[str, set[int]]    # table_name → 已完成的分块索引集合
    created_at: str                          # 创建时间
```

## 分块策略

### 切分键自动检测

| 数据库 | 检测方式 |
|--------|----------|
| PostgreSQL | `information_schema.table_constraints` + `key_column_usage` 查主键列 |
| ClickHouse | `system.columns` 中 `is_in_primary_key=1` 查主键列 |

- 多列主键选第一列作为切分键
- 无主键：报错要求手动指定 `chunk_key`
- 自动检测失败时回退到要求手动指定

### 分块方式

- **整型键**：`SELECT MIN(k), MAX(k)` 获取范围 → 等间距分块 `WHERE k >= start AND k < end`
- **时间戳键**：`SELECT MIN(k), MAX(k)` 获取范围 → 按时间区间分片，每片用 LIMIT chunk_size 确认末端精确值（避免数据密度不均）
- **UUID/字符串键**：`MIN/MAX` 获取范围 → 使用 keyset pagination（`WHERE k > last_seen ORDER BY k LIMIT n`），避免 OFFSET 在大数据量下性能退化

### SQL 生成

**条件模式 (mode=where) + 分块:**

```sql
-- PostgreSQL
SELECT * FROM "schema"."table"
WHERE chunk_key >= 0 AND chunk_key < 100000
  AND user_where_clause
ORDER BY chunk_key

-- ClickHouse
SELECT * FROM database.table
WHERE chunk_key >= 0 AND chunk_key < 100000
  AND user_where_clause
ORDER BY chunk_key
FORMAT CSVWithNames
```

**SQL 模式 (mode=sql) + 手动指定切分键：**

用户手写 SQL 包装为子查询，外层加 chunk 范围：

```sql
SELECT * FROM (
    <user_custom_sql>
) AS _sub
WHERE chunk_key >= 0 AND chunk_key < 100000
ORDER BY chunk_key
```

SQL 模式必须手动指定 `chunk_key`（必须是结果集中的列），否则拒绝执行。

## 核心模块重构

### 目录结构

```
src/core/
  migrator.py                 保留，变为薄入口（内部调用 MigrationOrchestrator）
  migration/                  新增子包
    __init__.py
    models.py                 MigrationCondition, ChunkSpec, MigrationMeta
    chunk_strategy.py         切分键检测、范围探测、分块列表计算
                                compute_chunks(adapter, client, table, cond) → list[ChunkSpec]
                                detect_chunk_key(adapter, client, table) → str
                                probe_range(adapter, client, table, chunk_key) → (min_val, max_val)
    orchestrator.py           分块循环、重试、断点、恢复
    resume_manager.py         断点文件读写
```

### MigrationOrchestrator — 核心编排器

```python
class MigrationOrchestrator:
    def __init__(self, src_config, dst_config, conditions, truncate_before=True,
                 resume_from=None, logger=None,
                 progress_callback: Callable[[ChunkProgress], None] | None = None): ...

    def run(self) -> dict:
        """与现有 migrate_tables() 返回格式兼容"""

    def _migrate_table(self, cond: MigrationCondition) -> TableMigrationResult:
        """单表迁移：
        1. chunk_strategy.compute_chunks(adapter, client, cond) → [ChunkSpec]
        2. for chunk in chunks:
             - 断点文件已有 → skip
             - export_chunk(chunk) → CSV
             - import_chunk(chunk, CSV, is_first_chunk=is_first_chunk_of_this_migration)
             - 成功 → mark chunk done → write checkpoint → progress_callback
             - 失败 → retry(max 3) → if still fail, mark failed, continue
        3. per-run temp dir cleanup 由 run() 统一管理
        """

    def _export_chunk(self, adapter, client, table, chunk) -> str: ...

    def _import_chunk(self, adapter, client, table, csv_path, is_first_chunk) -> None: ...

    def _resolve_truncate(self, resume_from: str | None, is_first_chunk: bool) -> bool:
        """首次全新迁移且 truncate_before=True 且是首 chunk → truncate；
        从断点恢复 → 永不 truncate（中间 chunks 不复 truncate）"""
```

### 向后兼容

`core/migrator.py: migrate_tables()` 签名不变，内部将 `table_names` 转为 `MigrationCondition` 列表，委托给 `MigrationOrchestrator.run()`。现有 GUI 页面和测试无需修改。

### 进度回调

Orchestrator 支持 `progress_callback`，每完成一个 chunk 时回调，GUI 层用于更新进度条：

```python
def on_chunk_done(table: str, chunk_index: int, total_chunks: int, rows: int): ...
```

## Adapter 层改动

### export_csv 接口扩展

```python
def export_csv(
    self,
    client,
    db_config: dict,
    table: str,                           # 改为单表（分块粒度）
    export_dir: str,
    schema: str = "",
    where_clause: str = "",               # 新增
    custom_sql: str = "",                 # 新增
    chunk_key: str = "",                  # 新增
    chunk_start: Any = None,              # 新增
    chunk_end: Any = None,                # 新增
    include_header: bool = True,
    logger=None,
) -> dict:
```

SQL 构建优先级：custom_sql > where_clause + chunk > 仅 chunk > 整表导出。

各 adapter 抽取 `_build_chunked_query()` 私有方法。

### import_csv 接口扩展

新增 `is_first_chunk: bool = False` 参数：

- `truncate_before=True` 且 `is_first_chunk=False` → 不 truncate
- `truncate_before=True` 且 `is_first_chunk=True` → truncate

### 向后兼容

现有 caller 不传新参数 → 行为不变（整表导出/导入）。

## GUI

### 左侧面板布局

- 源库/目标库选择器（保持不变）
- 全局设置：TRUNCATE 开关、默认分块行数
- 表列表（可折叠行）：
  - `[+ 添加表]` 按钮添加
  - 每行可展开 → 模式选择（条件/SQL）、WHERE/自定义SQL 输入、切分键、分块行数覆盖
  - `[×]` 删除
- 开始/暂停/继续按钮

### 模式联动

- 条件模式：WHERE 输入框（单行），chunk_key 可留空自动检测
- SQL 模式：自定义 SQL 输入框（多行），chunk_key 必填（空时红色提示）

### 右侧日志面板增强

- 总进度条（按块数/行数）
- 逐块日志（导出完成/导入完成/重试/失败）
- 每块耗时

### 断点恢复

1. 启动迁移 → 生成 `migration_id` + `MigrationMeta` → 写入 `~/.db_migrator_resume/{id}.json`
2. 每完成一个 chunk → 更新断点文件
3. 启动时检测未完成的 migration → 提示用户「重新开始」或「从断点恢复」
4. 全部完成后 → 删除断点文件

## 错误处理

- 切分键无法自动检测 → 报错，要求手动指定
- SQL 模式未指定 chunk_key → 拒绝执行
- 单个 chunk 失败 → 重试 3 次（指数退避 1s/2s/4s）
- 重试全失败 → 标记该 chunk 失败，记录到结果，继续后续 chunk
- 单表全部 chunk 失败 → 表标记为迁移失败
- 断点文件损坏 → 警告并从头开始

## 测试要点

- 条件模式 + 自动检测切分键
- SQL 模式 + 手动指定切分键
- 分块边界（首块、中间块、末块）
- 异常分支：
  - 无主键表报错
  - SQL 模式缺 chunk_key 拒绝
  - chunk 失败重试机制
  - 断点恢复（模拟中断后重启）
- 不同 chunk_key 类型（int/timestamp/uuid）
- 向后兼容：旧的 migrate_tables() 调用不受影响
