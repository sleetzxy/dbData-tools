# 数据迁移流式重构与通用分块 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构数据迁移为默认流式零落盘传输，支持 PG/CK 全组合；分块由用户指定时间/分区范围确定性生成（不探测数据）；保留断点续传与 CSV 兜底。

**Architecture:** 新增 `SplitConfig` + `split_strategy` 生成分块；`TransferPipeline` 按 DB 组合路由（PG CopyBridge、CK remote、异构 MemoryBudget batch）；`MigrationOrchestrator` 委托 Pipeline，STREAM 模式不建临时目录。

**Tech Stack:** Python 3.10+, psycopg2, clickhouse-connect, CustomTkinter, pytest + pytest-mock

**Spec:** `docs/superpowers/specs/2026-05-25-migration-stream-redesign-design.md`

---

## 文件映射

| 文件 | 职责 |
|------|------|
| `src/core/migration/models.py` | SplitMode, BindType, SplitConfig, ChunkSpec 扩展, MemoryBudgetConfig |
| `src/core/migration/split_strategy.py` | **新建** 日历/分区值/物理分区 chunk 生成 |
| `src/core/migration/memory_budget.py` | **新建** 采样行宽、batch_rows、buffer 字节 |
| `src/core/migration/copy_bridge.py` | **新建** PG CopyBridge file-like |
| `src/core/migration/transfer_pipeline.py` | **新建** 传输路由与降级 |
| `src/core/migration/orchestrator.py` | 委托 Pipeline；STREAM 跳过 temp_dir |
| `src/core/migration/chunk_strategy.py` | 仅保留 KEY_RANGE + 旧 API 转发 |
| `src/db/adapters/postgresql_adapter.py` | CopyBridge 集成；废弃整块 StringIO |
| `src/db/adapters/clickhouse_adapter.py` | `remote_transfer`；重写 `stream_read` |
| `src/gui/pages/database/migrator.py` | 通用五步分块 UI + chunk 预览 |
| `tests/test_split_strategy.py` | **新建** |
| `tests/test_copy_bridge.py` | **新建** |
| `tests/test_transfer_pipeline.py` | **新建** |
| `tests/test_memory_budget.py` | **新建** |

---

### Task 1: 数据模型 — SplitConfig / ChunkSpec 扩展

**Files:**
- Modify: `src/core/migration/models.py`
- Modify: `src/core/migration/__init__.py`
- Modify: `tests/test_migration_models.py`

- [ ] **Step 1: 写失败测试**

```python
def test_split_config_defaults() -> None:
    from core.migration.models import SplitConfig, SplitMode

    cfg = SplitConfig()
    assert cfg.mode == SplitMode.PARTITION_VALUE
    assert cfg.batch_size == 1


def test_chunk_spec_has_label_and_where_sql() -> None:
    from core.migration.models import ChunkSpec

    c = ChunkSpec(chunk_index=0, label="20240601~20240607", where_sql="p >= 1")
    assert c.physical_targets == []
```

- [ ] **Step 2: 运行测试确认 FAIL**

Run: `pytest tests/test_migration_models.py -v`

- [ ] **Step 3: 实现 SplitMode, BindType, SplitConfig, ChunkSpec 扩展, MemoryBudgetConfig**

- [ ] **Step 4: 运行测试 PASS**

- [ ] **Step 5: Commit**

```bash
git add src/core/migration/models.py src/core/migration/__init__.py tests/test_migration_models.py
git commit -m "feat(migration): 添加 SplitConfig 与 ChunkSpec 扩展字段"
```

---

### Task 2: 分块生成 — split_strategy（无数据探测）

**Files:**
- Create: `src/core/migration/split_strategy.py`
- Create: `tests/test_split_strategy.py`

- [ ] **Step 1: 日历切分测试**

```python
@pytest.mark.parametrize(
    "start,end,granularity,batch,expected_count",
    [
        ("2024-06-01", "2024-06-30", "day", 7, 5),
        ("2024-01-01", "2024-12-31", "month", 3, 4),
    ],
)
def test_compute_calendar_chunks(start, end, granularity, batch, expected_count):
    ...
```

- [ ] **Step 2: 分区值 yyyyMMdd 测试**

```python
def test_compute_partition_value_chunks_yyyyMMdd() -> None:
    cfg = SplitConfig(
        mode=SplitMode.PARTITION_VALUE,
        range_start="20240601",
        range_end="20240630",
        value_format="yyyyMMdd",
        bind_type=BindType.COLUMN,
        bind_target="p_date",
        batch_size=7,
    )
    chunks = compute_split_chunks(cfg)
    assert len(chunks) == 5
    assert "20240601" in chunks[0].label
    assert "p_date >= 20240601" in chunks[0].where_sql
```

- [ ] **Step 3: 物理分区模板测试**

```python
def test_compute_physical_template_chunks() -> None:
    cfg = SplitConfig(
        mode=SplitMode.PHYSICAL_PARTITION,
        range_start="20240601",
        range_end="20240606",
        value_format="yyyyMMdd",
        bind_type=BindType.NAME_TEMPLATE,
        bind_target="orders_{yyyyMMdd}",
        batch_size=2,
    )
    chunks = compute_split_chunks(cfg)
    assert chunks[0].physical_targets == ["orders_20240601", "orders_20240602"]
```

- [ ] **Step 4: 实现 `compute_split_chunks(cfg) -> list[ChunkSpec]`**

含：`parse_range`、`advance_by_granularity`、`build_where_sql`（PG/CH 方言参数化接口）

- [ ] **Step 5: 实现 `merge_extra_where(where_sql, extra_where)`**

- [ ] **Step 6: pytest PASS**

Run: `pytest tests/test_split_strategy.py -v`

- [ ] **Step 7: Commit**

```bash
git add src/core/migration/split_strategy.py tests/test_split_strategy.py
git commit -m "feat(migration): 添加确定性分块策略 split_strategy"
```

---

### Task 3: 物理分区元数据列表（可选查库）

**Files:**
- Modify: `src/core/migration/split_strategy.py`
- Modify: `src/db/adapters/postgresql_adapter.py`
- Modify: `src/db/adapters/clickhouse_adapter.py`
- Modify: `tests/test_split_strategy.py`

- [ ] **Step 1: 写 mock 测试 — CH system.parts 列表**

- [ ] **Step 2: 实现 `list_physical_partitions(adapter, client, parent_table, schema, range) -> list[str]`**

- [ ] **Step 3: `compute_split_chunks` 在 METADATA_LIST 模式调用**

- [ ] **Step 4: pytest PASS + Commit**

```bash
git commit -m "feat(migration): 物理分区元数据列表模式"
```

---

### Task 4: MemoryBudget

**Files:**
- Create: `src/core/migration/memory_budget.py`
- Create: `tests/test_memory_budget.py`

- [ ] **Step 1: 测试 batch_rows 计算与 clamp**

```python
def test_compute_batch_rows_wide_table() -> None:
    budget = MemoryBudget(MemoryBudgetConfig(limit_mb=512))
    rows = budget.compute_batch_rows(avg_row_bytes=50_000)
    assert rows == 100  # min clamp
```

- [ ] **Step 2: 实现采样与 `buffer_bytes` 属性**

- [ ] **Step 3: pytest PASS + Commit**

---

### Task 5: PG CopyBridge

**Files:**
- Create: `src/core/migration/copy_bridge.py`
- Create: `tests/test_copy_bridge.py`

- [ ] **Step 1: 测试 CopyBridge read/write 有界队列**

```python
def test_copy_bridge_bounded_size() -> None:
    bridge = CopyBridge(max_bytes=1024)
    bridge.write(b"x" * 2048)  # 应阻塞或背压，不无限增长
    ...
```

- [ ] **Step 2: 实现 `CopyBridge`（queue + 线程安全 file-like）**

- [ ] **Step 3: 实现 `copy_via_bridge(src_cur, dst_cur, src_sql, copy_in_sql, max_buffer_bytes) -> int`**

- [ ] **Step 4: pytest PASS + Commit**

```bash
git commit -m "feat(migration): PG CopyBridge 有界 COPY 管道"
```

---

### Task 6: PostgreSQL 适配器 — 集成 CopyBridge

**Files:**
- Modify: `src/db/adapters/postgresql_adapter.py`
- Modify: `tests/test_orchestrator_stream.py` 或新建 `tests/test_pg_copy_bridge.py`

- [ ] **Step 1: 用 CopyBridge 替换 `copy_stream_transfer` 整块 StringIO 实现**

- [ ] **Step 2: 新增 `build_chunk_where(chunk: ChunkSpec) -> sql.Composable` 或复用 where_sql**

- [ ] **Step 3: mock 测试 COPY 调用次数与行数**

- [ ] **Step 4: pytest PASS + Commit**

---

### Task 7: ClickHouse 适配器 — remote 直传 + 真流式读

**Files:**
- Modify: `src/db/adapters/clickhouse_adapter.py`
- Create: `tests/test_ch_remote_transfer.py`

- [ ] **Step 1: 测试 `build_remote_insert_sql(pull=True, chunk, src_config, dst_table)`**

- [ ] **Step 2: 实现 `remote_transfer(dst_client, src_config, dst_table, chunk, settings) -> int`**

含 Pull/Push、SETTINGS、物理 `PARTITION 'name'`

- [ ] **Step 3: 重写 `stream_read` 使用 `raw_stream` + 分块解析（禁止全量 result_rows）**

- [ ] **Step 4: pytest PASS + Commit**

```bash
git commit -m "feat(migration): CK remote 直传与 raw_stream 流式读"
```

---

### Task 8: TransferPipeline 统一路由

**Files:**
- Create: `src/core/migration/transfer_pipeline.py`
- Create: `tests/test_transfer_pipeline.py`

- [ ] **Step 1: 测试路由矩阵（mock adapters）**

```python
@pytest.mark.parametrize(
    "src,dst,mode,expected_method",
    [
        ("postgresql", "postgresql", TransferMode.STREAM, "copy_via_bridge"),
        ("clickhouse", "clickhouse", TransferMode.STREAM, "remote_transfer"),
        ("postgresql", "clickhouse", TransferMode.STREAM, "hetero_stream"),
    ],
)
def test_pipeline_routes(...): ...
```

- [ ] **Step 2: 实现 `TransferPipeline.transfer_chunk(...) -> int`**

- [ ] **Step 3: CSV 降级分支调用 export_csv/import_csv**

- [ ] **Step 4: pytest PASS + Commit**

---

### Task 9: Orchestrator 重构

**Files:**
- Modify: `src/core/migration/orchestrator.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/test_orchestrator_stream.py`

- [ ] **Step 1: 测试 STREAM 模式不创建 temp_dir（mock tempfile.mkdtemp）**

- [ ] **Step 2: `compute_chunks` 改为调用 `compute_split_chunks(cond.split)`；KEY_RANGE 走旧 chunk_strategy**

- [ ] **Step 3: `_migrate_table` 委托 `TransferPipeline`；移除 `_stream_chunk` 内联逻辑**

- [ ] **Step 4: 默认 `transfer_mode=TransferMode.STREAM`**

- [ ] **Step 5: 断点保存 chunk `label`**

- [ ] **Step 6: pytest 全量 migration 测试 PASS**

Run: `pytest tests/test_orchestrator.py tests/test_orchestrator_stream.py -v`

- [ ] **Step 7: Commit**

```bash
git commit -m "refactor(migration): Orchestrator 委托 TransferPipeline"
```

---

### Task 10: 配置兼容层

**Files:**
- Create: `src/core/migration/config_compat.py`
- Modify: `tests/test_migration_models.py`

- [ ] **Step 1: 测试旧 JSON 无 split 字段时映射为 KEY_RANGE**

```python
def test_legacy_condition_to_split_config() -> None:
    cond = MigrationCondition(table_name="t", mode="where", chunk_key="id", chunk_size=1000, where_clause="x=1")
    split = legacy_to_split_config(cond)
    assert split.mode == SplitMode.KEY_RANGE
    assert split.extra_where == "x=1"
```

- [ ] **Step 2: 实现 `legacy_to_split_config` / `split_config_to_legacy`**

- [ ] **Step 3: GUI `apply_config` 使用兼容层 + Commit**

---

### Task 11: GUI — 通用五步分块界面

**Files:**
- Modify: `src/gui/pages/database/migrator.py`

- [ ] **Step 1: 重构 `_TableCard` 展开面板为五步布局（范围/方式/绑定/批量/过滤）**

- [ ] **Step 2: 实现 `_preview_chunks()` 调用 `compute_split_chunks` 更新预览标签**

- [ ] **Step 3: 全局设置：内存上限 MB、CK SETTINGS 折叠面板**

- [ ] **Step 4: `get_config_dict` / `apply_config` 读写 `split` 结构**

- [ ] **Step 5: 手工验证 `python main_gui.py` 迁移页配置保存与预览**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(gui): 迁移页通用分块配置与 chunk 预览"
```

---

### Task 12: migrator 入口与默认 STREAM

**Files:**
- Modify: `src/core/migrator.py`

- [ ] **Step 1: 默认 `transfer_mode=TransferMode.STREAM`**

- [ ] **Step 2: 传入 `MemoryBudgetConfig` 到 Orchestrator**

- [ ] **Step 3: `pytest tests/test_migrator.py -v` + Commit**

---

### Task 13: 集成验证与文档

**Files:**
- Modify: `README.md`（迁移章节简要更新）

- [ ] **Step 1: 全量测试**

```bash
python -m compileall src/core src/db src/gui src/utils main_gui.py
pytest
```

- [ ] **Step 2: 更新 README 迁移说明（分块模式、PG/CK 路径、内存设置）**

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: 更新数据迁移流式与分块配置说明"
```

---

## 实施顺序建议

```
Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13
         ↑ 分块策略优先，后续传输层依赖 ChunkSpec.where_sql / physical_targets
```

## 手工验证清单

1. PG→PG：流式迁移 10 万行，确认无 `db_migrate_*` 临时目录
2. CK→CK：跨实例 remote，按 yyyyMMdd 每 7 天一批，中断后续传
3. PG→CK：宽表 MemoryBudget 自动减小 batch
4. 物理分区模板：`orders_{yyyyMMdd}` 预览 chunk 列表正确
5. CSV 兜底：显式选 CSV 模式，确认临时文件生成且迁移成功

## 风险提醒

- CopyBridge 线程与 psycopg2 连接线程安全：每 chunk 用独立 cursor，不跨线程共享 connection
- CK `remote()` 需目标能访问源；Push 模式需 GUI 明确提示
- 旧配置无 `split` 时走 KEY_RANGE，行为与现网一致
