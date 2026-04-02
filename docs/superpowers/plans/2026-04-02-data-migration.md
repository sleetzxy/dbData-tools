# 数据迁移功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增数据迁移工具页，支持在 PostgreSQL / ClickHouse 之间（同构或异构）迁移指定多张表的数据，通过临时 CSV 中转，用户可选择是否迁移前清空目标表。

**Architecture:** 中转 CSV 方案——先用源库 adapter 将数据导出到系统临时目录，再用目标库 adapter 从临时目录导入，迁移结束后自动清理临时文件。核心逻辑放在 `core/migrator.py`，GUI 页面继承 `BaseToolPage`，两个 adapter 的 `import_csv` 新增 `truncate_before` 参数实现追加/覆盖切换（默认 `True`，向后兼容）。

**Tech Stack:** Python 3, customtkinter, psycopg2, clickhouse-connect, pytest（单元测试用 mock client），compileall 语法检查。

---

## File Structure / Responsibilities

- Modify: `db/adapters/postgresql_adapter.py` — `import_csv` 新增 `truncate_before: bool = True` 参数
- Modify: `db/adapters/clickhouse_adapter.py` — 同上
- Create: `core/migrator.py` — `migrate_tables()` 核心迁移函数
- Create: `gui/pages/database/migrator.py` — `MigratorPage(BaseToolPage)` 迁移页面
- Modify: `main_gui.py` — 注册菜单按钮、导入、load 方法、changelog v1.4.0
- Modify: `README.md` — 功能列表补充数据迁移说明
- Create: `tests/test_migrator.py` — 迁移核心逻辑单元测试

---

## Task 1: 给两个 adapter 的 import_csv 增加 truncate_before 参数

**Files:**
- Modify: `db/adapters/postgresql_adapter.py`
- Modify: `db/adapters/clickhouse_adapter.py`
- Test: `tests/test_adapter_dispatch.py`（已有，添加新 case）

- [ ] **Step 1: 在 `db/adapters/postgresql_adapter.py` 的 `import_csv` 签名中增加参数**

在 `def import_csv(self, client, db_config, table_names, data_dir, schema="public", pre_sql_file="", need_backup=False, logger=None)` 末尾插入 `truncate_before: bool = True`（放在 `logger` 之前）：

```python
def import_csv(
    self,
    client,
    db_config,
    table_names,
    data_dir,
    schema: str = "public",
    pre_sql_file: str = "",
    need_backup: bool = False,
    truncate_before: bool = True,
    logger=None,
) -> dict:
```

- [ ] **Step 2: 将 PostgreSQL adapter 中无条件的 TRUNCATE 改为条件执行**

定位 `db/adapters/postgresql_adapter.py` 中执行 TRUNCATE 的代码块（约第 408-414 行），用 `if truncate_before:` 包裹：

```python
if truncate_before:
    truncate_sql = sql.SQL("TRUNCATE TABLE {}.{}").format(
        sql.Identifier(schema),
        sql.Identifier(table),
    )
    cursor.execute(truncate_sql)
    if logger:
        logger.info(f"Table {schema}.{table} truncated")
```

- [ ] **Step 3: 在 `db/adapters/clickhouse_adapter.py` 的 `import_csv` 做同样改动**

签名增加 `truncate_before: bool = True`（放在 `logger` 之前），定位执行 `client.command(f"TRUNCATE TABLE {qualified}")` 的行，用 `if truncate_before:` 包裹：

```python
if truncate_before:
    client.command(f"TRUNCATE TABLE {qualified}")
```

- [ ] **Step 4: 验证语法**

```bash
python -m compileall db/adapters/postgresql_adapter.py db/adapters/clickhouse_adapter.py
```

Expected: `Compiling ... ok`（无错误）

- [ ] **Step 5: 在 `tests/test_adapter_dispatch.py` 末尾追加两个 truncate_before 测试**

```python
def test_postgresql_import_csv_truncate_before_false_skips_truncate():
    """truncate_before=False 时不应执行 TRUNCATE，验证参数被接受不报错"""
    from db.adapters.postgresql_adapter import PostgreSQLAdapter
    adapter = PostgreSQLAdapter()

    class FakeCursor:
        def __init__(self):
            self.executed = []
        def execute(self, sql, params=None):
            self.executed.append(str(sql))
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class FakeConn:
        def __init__(self):
            self.autocommit = True
            self._cursor = FakeCursor()
        def cursor(self): return self._cursor

    import tempfile, os
    tmp = tempfile.mkdtemp()
    csv_file = os.path.join(tmp, "t1.csv")
    with open(csv_file, "w", encoding="utf-8") as f:
        f.write("id,name\n1,alice\n")

    result = adapter.import_csv(
        client=FakeConn(),
        db_config={"database": "testdb"},
        table_names=["t1"],
        data_dir=tmp,
        schema="public",
        truncate_before=False,
        logger=None,
    )
    # TRUNCATE 不应出现在执行列表中
    executed_sql = " ".join(FakeConn()._cursor.executed)
    assert "TRUNCATE" not in executed_sql
    import shutil; shutil.rmtree(tmp)


def test_clickhouse_import_csv_truncate_before_false_skips_truncate():
    """ClickHouse truncate_before=False 时不执行 TRUNCATE"""
    from db.adapters.clickhouse_adapter import ClickHouseAdapter
    adapter = ClickHouseAdapter()

    class FakeClient:
        def __init__(self):
            self.commands = []
        def command(self, sql, data=None):
            self.commands.append(sql)

    import tempfile, os
    tmp = tempfile.mkdtemp()
    csv_file = os.path.join(tmp, "t1.csv")
    with open(csv_file, "wb") as f:
        f.write(b"id,name\n1,alice\n")

    fake_client = FakeClient()
    result = adapter.import_csv(
        client=fake_client,
        db_config={"database": "testdb"},
        table_names=["t1"],
        data_dir=tmp,
        truncate_before=False,
        logger=None,
    )
    assert not any("TRUNCATE" in c for c in fake_client.commands)
    import shutil; shutil.rmtree(tmp)
```

- [ ] **Step 6: 运行新增的测试**

```bash
python -m pytest tests/test_adapter_dispatch.py::test_postgresql_import_csv_truncate_before_false_skips_truncate tests/test_adapter_dispatch.py::test_clickhouse_import_csv_truncate_before_false_skips_truncate -v
```

Expected: 2 passed

- [ ] **Step 7: 运行完整测试套件确认无回归**

```bash
python -m pytest tests/ -v
```

Expected: 全部 PASS（排除需要真实数据库连接的集成测试）

- [ ] **Step 8: Commit**

```bash
git add db/adapters/postgresql_adapter.py db/adapters/clickhouse_adapter.py tests/test_adapter_dispatch.py
git commit -m "feat: add truncate_before param to import_csv in both adapters"
```

---

## Task 2: 创建 core/migrator.py

**Files:**
- Create: `core/migrator.py`
- Create: `tests/test_migrator.py`

- [ ] **Step 1: 在 `tests/test_migrator.py` 中写失败测试**

```python
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
    """验证 truncate_before=False 被正确透传"""
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
```

- [ ] **Step 2: 运行测试确认失败（core/migrator.py 不存在）**

```bash
python -m pytest tests/test_migrator.py -v
```

Expected: ImportError / ModuleNotFoundError

- [ ] **Step 3: 创建 `core/migrator.py`**

```python
"""
数据迁移核心逻辑

将源库中指定的多张表通过临时 CSV 中转迁移到目标库。
支持 PostgreSQL / ClickHouse 同构及异构迁移。
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def migrate_tables(
    src_config: Dict[str, Any],
    dst_config: Dict[str, Any],
    table_names: List[str],
    truncate_before: bool = True,
    src_adapter: Optional[Any] = None,
    dst_adapter: Optional[Any] = None,
    logger: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    将源库中指定的多张表迁移到目标库。

    Args:
        src_config: 源库连接配置（含 db_type）
        dst_config: 目标库连接配置（含 db_type）
        table_names: 要迁移的表名列表
        truncate_before: 迁移前是否清空目标表
        src_adapter: 测试用注入，生产时自动从 db_type 获取
        dst_adapter: 测试用注入，生产时自动从 db_type 获取
        logger: 日志记录器

    Returns:
        {
            "success": bool,
            "migrated_tables": [{"name": str, "rows": int}, ...],
            "error_tables": [{"name": str, "error": str}, ...],
            "total_rows": int,
        }
    """
    result: Dict[str, Any] = {
        "success": True,
        "migrated_tables": [],
        "error_tables": [],
        "total_rows": 0,
    }

    table_names = [t.strip() for t in table_names if t.strip()]
    if not table_names:
        result["success"] = False
        result["error"] = "未指定要迁移的表名"
        return result

    # 获取 adapter
    if src_adapter is None or dst_adapter is None:
        from db.adapters import get_adapter_for_config
        if src_adapter is None:
            src_adapter = get_adapter_for_config(src_config)
        if dst_adapter is None:
            dst_adapter = get_adapter_for_config(dst_config)

    tmp_dir = tempfile.mkdtemp(prefix="db_migrator_")
    src_client = None
    dst_client = None

    try:
        # 在循环外建立连接
        src_client = src_adapter.create_client(src_config)
        dst_client = dst_adapter.create_client(dst_config)

        src_schema = src_config.get("schema", "")
        dst_schema = dst_config.get("schema", "")

        for table in table_names:
            table_tmp_dir = os.path.join(tmp_dir, table)
            os.makedirs(table_tmp_dir, exist_ok=True)
            try:
                # 导出
                export_result = src_adapter.export_csv(
                    client=src_client,
                    db_config=src_config,
                    tables=[table],
                    export_dir=table_tmp_dir,
                    schema=src_schema,
                    include_header=True,
                    logger=logger,
                )
                if not export_result.get("success", True) and export_result.get("error_tables"):
                    raise RuntimeError(
                        export_result["error_tables"][0].get("error", "导出失败")
                    )

                exported = export_result.get("exported_tables", [])
                row_count = exported[0].get("rows", 0) if exported else 0

                # 导入
                import_result = dst_adapter.import_csv(
                    client=dst_client,
                    db_config=dst_config,
                    table_names=[table],
                    data_dir=table_tmp_dir,
                    schema=dst_schema,
                    truncate_before=truncate_before,
                    logger=logger,
                )
                if not import_result.get("success", True) and import_result.get("error_tables"):
                    err = import_result["error_tables"][0]
                    raise RuntimeError(err.get("error", "导入失败"))

                result["migrated_tables"].append({"name": table, "rows": row_count})
                result["total_rows"] += row_count

                if logger:
                    logger.info(f"表 {table} 迁移完成，共 {row_count} 行")

            except Exception as exc:
                error_msg = str(exc)
                if logger:
                    logger.error(f"表 {table} 迁移失败: {error_msg}")
                result["error_tables"].append({"name": table, "error": error_msg})
                result["success"] = False
            finally:
                # 清理该表的临时目录
                shutil.rmtree(table_tmp_dir, ignore_errors=True)

    except Exception as exc:
        error_msg = f"迁移过程发生错误: {exc}"
        if logger:
            logger.error(error_msg)
        result["success"] = False
        result["error"] = error_msg
    finally:
        if src_client is not None:
            try:
                src_adapter.close_client(src_client)
            except Exception:
                pass
        if dst_client is not None:
            try:
                dst_adapter.close_client(dst_client)
            except Exception:
                pass
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return result
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_migrator.py -v
```

Expected: 4 passed

- [ ] **Step 5: 语法检查**

```bash
python -m compileall core/migrator.py
```

Expected: `Compiling ... ok`

- [ ] **Step 6: Commit**

```bash
git add core/migrator.py tests/test_migrator.py
git commit -m "feat: add core/migrator.py with migrate_tables function"
```

---

## Task 3: 创建 gui/pages/database/migrator.py

**Files:**
- Create: `gui/pages/database/migrator.py`
- Modify: `gui/pages/database/__init__.py`（如需导出）

- [ ] **Step 1: 创建 `gui/pages/database/migrator.py`**

```python
"""
数据迁移页面 - 支持 PostgreSQL / ClickHouse 同构及异构迁移
"""
import tkinter as tk
from tkinter import messagebox

from gui.base import BaseToolPage
from gui.components import ConnectionSelector
from gui.widgets.labels import TitleLabel, StyledLabel
from gui.widgets.buttons import PrimaryButton
from gui.widgets.scrolled_texts import StyledScrolledText
from core.migrator import migrate_tables
import logging

logger = logging.getLogger(__name__)


class MigratorPage(BaseToolPage):
    """
    数据迁移页面

    左侧：源库选择、目标库选择、表名输入、truncate 选项、开始按钮
    右侧：标准日志面板
    """

    CONFIG_FILE = "~/.db_migrator_config.json"

    def __init__(self, root):
        super().__init__(
            root=root,
            config_file=self.CONFIG_FILE,
            log_title="📋 迁移日志",
            core_logger=logger,
        )

    def setup_left_panel_content(self, parent):
        """设置左侧面板内容"""
        TitleLabel(parent, text="🔁 数据迁移").pack(anchor="w", pady=(0, 15))

        # 源数据库连接
        StyledLabel(parent, text="源数据库连接").pack(anchor="w", pady=(0, 3))
        self.src_selector = ConnectionSelector(parent, label_text="")
        self.src_selector.pack(fill="x", pady=(0, 15))

        # 目标数据库连接
        StyledLabel(parent, text="目标数据库连接").pack(anchor="w", pady=(0, 3))
        self.dst_selector = ConnectionSelector(parent, label_text="")
        self.dst_selector.pack(fill="x", pady=(0, 15))

        # 设置兼容 ConnectionMixin 的引用（取 src 作为默认连接引用）
        self.connection_var = self.src_selector.connection_var
        self.connection_menu = self.src_selector.connection_menu

        # 表名输入
        StyledLabel(parent, text="迁移的表名（多个用逗号或换行分隔）").pack(
            anchor="w", pady=(0, 3)
        )
        table_container = self.ctk.CTkFrame(
            parent,
            fg_color=self.idea_dark_colors["card_bg"],
            corner_radius=8,
        )
        table_container.pack(fill="both", pady=(0, 15))
        self.text_tables = StyledScrolledText(table_container)
        self.text_tables.pack(fill="both", expand=True, padx=5, pady=5)
        self.text_tables.configure(height=10)

        # TRUNCATE 选项
        truncate_frame = self.ctk.CTkFrame(parent, fg_color="transparent")
        truncate_frame.pack(anchor="w", pady=(0, 15))
        self.truncate_var = tk.BooleanVar(value=True)
        self.ctk.CTkCheckBox(
            truncate_frame,
            text="迁移前清空目标表（TRUNCATE）",
            variable=self.truncate_var,
            font=("Microsoft YaHei", 10),
            text_color=self.idea_dark_colors["text_primary"],
            fg_color=self.idea_dark_colors["gray_button"],
            hover_color=self.idea_dark_colors["gray_button_hover"],
            border_color=self.idea_dark_colors["gray_button_border"],
            checkmark_color=self.idea_dark_colors["text_primary"],
        ).pack(side="left")

        # 开始迁移按钮
        self.migrate_button = PrimaryButton(
            parent,
            text="🚀 开始迁移",
            command=self.start_task,
        )
        self.migrate_button.pack(anchor="w", fill="x", pady=(10, 0))

    def get_config_dict(self):
        """返回要保存的配置字典"""
        return {
            "src_connection_name": self.src_selector.connection_var.get(),
            "dst_connection_name": self.dst_selector.connection_var.get(),
            "table_names": self.text_tables.get("1.0", tk.END).strip(),
            "truncate_before": self.truncate_var.get(),
        }

    def apply_config(self, config):
        """应用加载的配置"""
        try:
            src_name = config.get("src_connection_name", "")
            if src_name:
                self.src_selector.set_value(src_name)

            dst_name = config.get("dst_connection_name", "")
            if dst_name:
                self.dst_selector.set_value(dst_name)

            table_names = config.get("table_names", "")
            self.text_tables.delete("1.0", tk.END)
            self.text_tables.insert(tk.END, table_names)

            self.truncate_var.set(config.get("truncate_before", True))

            if self.logger:
                self.logger.info("配置已加载")
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载配置失败: {e}")

    def _get_connection_config_by_selector(self, selector):
        """根据 selector 的选中值查找连接配置"""
        selected = selector.connection_var.get()
        if not selected or selected in ("", "无可用连接"):
            return None
        for conn in self.connections:
            label = f"{conn.get('name', '未命名连接')} ({conn.get('host', '')}:{conn.get('port', '')})"
            if label == selected:
                return conn
        return None

    def start_task(self):
        """启动迁移任务"""
        self.run_task(
            button_widget=self.migrate_button,
            button_text="🚀 开始迁移",
            running_text="迁移中...",
        )

    def execute_task(self):
        """在后台线程中执行迁移"""
        if not self.validate():
            return {"success": False, "error": "参数验证失败"}

        src_config = self._get_connection_config_by_selector(self.src_selector)
        dst_config = self._get_connection_config_by_selector(self.dst_selector)

        if src_config is None:
            return {"success": False, "error": "请选择源数据库连接"}
        if dst_config is None:
            return {"success": False, "error": "请选择目标数据库连接"}

        raw = self.text_tables.get("1.0", tk.END).strip()
        table_names = []
        for line in raw.split("\n"):
            table_names.extend([t.strip() for t in line.split(",") if t.strip()])

        truncate_before = self.truncate_var.get()

        if self.logger:
            self.logger.info(
                f"开始数据迁移: {src_config.get('name')} → {dst_config.get('name')}"
            )
            self.logger.info(f"迁移表: {', '.join(table_names)}")
            self.logger.info(f"迁移前清空目标表: {truncate_before}")

        result = migrate_tables(
            src_config=src_config,
            dst_config=dst_config,
            table_names=table_names,
            truncate_before=truncate_before,
            logger=self.logger,
        )

        if result.get("success"):
            self.logger.info(
                f"迁移完成: 成功 {len(result['migrated_tables'])} 张表，"
                f"共 {result['total_rows']} 行"
            )
        else:
            failed = result.get("error_tables", [])
            self.logger.error(
                f"迁移结束: 成功 {len(result['migrated_tables'])} 张，"
                f"失败 {len(failed)} 张"
            )

        return result

    def validate(self):
        """验证输入"""
        raw = self.text_tables.get("1.0", tk.END).strip()
        if not raw:
            messagebox.showerror("错误", "请输入要迁移的表名")
            return False
        return True

    def on_task_success(self, result):
        messagebox.showinfo("完成", f"数据迁移成功！共迁移 {result['total_rows']} 行数据。")

    def on_task_error(self, result):
        error_tables = result.get("error_tables", [])
        if error_tables:
            detail = "\n".join(
                f"• {t['name']}: {t['error']}" for t in error_tables
            )
            messagebox.showerror("部分表迁移失败", f"以下表迁移失败：\n{detail}")
        else:
            messagebox.showerror("错误", result.get("error", "迁移过程中发生错误"))
```

- [ ] **Step 2: 语法检查**

```bash
python -m compileall gui/pages/database/migrator.py
```

Expected: `Compiling ... ok`

- [ ] **Step 3: Commit**

```bash
git add gui/pages/database/migrator.py
git commit -m "feat: add MigratorPage for data migration GUI"
```

---

## Task 4: 在 main_gui.py 注册迁移功能 + 更新 changelog

**Files:**
- Modify: `main_gui.py`

- [ ] **Step 1: 在 `main_gui.py` 顶部导入区域添加 MigratorPage**

在现有导入行（约第 10 行 `from gui.pages.database.exporter import ExportDbApp`）后面插入：

```python
from gui.pages.database.migrator import MigratorPage
```

- [ ] **Step 2: 在 `tools_data` 列表的"数据库导出"条目后插入迁移按钮**

定位 `self.tools_data` 列表（约第 318-324 行），在 `("📦", "数据库导出", self.load_db_exporter),` 后插入：

```python
("🔁", "数据迁移", self.load_migrator),
```

- [ ] **Step 3: 添加 `load_migrator` 方法**

在 `load_db_exporter` 方法（约第 710-716 行）后紧接着添加：

```python
def load_migrator(self):
    """加载数据迁移工具（持久化页面切换）"""
    self._reset_menu_buttons()
    btn = self.command_to_button.get('load_migrator')
    if btn:
        btn.configure(fg_color=self.idea_dark_colors["button_hover"])
    self._show_page('migrator', builder=lambda parent: MigratorPage(parent))
```

- [ ] **Step 4: 在 `get_changelog_data()` 最前面插入 v1.4.0 条目**

定位 `get_changelog_data()` 方法（约第 448 行），在 `return [` 后的第一个 `{` 前插入：

```python
{
    "version": "1.4.0",
    "date": "2026-04-02",
    "changes": [
        "新增数据迁移功能，支持指定多表从源库迁移到目标库",
        "支持 PostgreSQL 与 ClickHouse 同构及异构迁移",
        "可选迁移前清空目标表（TRUNCATE）"
    ],
    "color": self.idea_dark_colors["accent"]
},
```

- [ ] **Step 5: 语法检查**

```bash
python -m compileall main_gui.py
```

Expected: `Compiling ... ok`

- [ ] **Step 6: Commit**

```bash
git add main_gui.py
git commit -m "feat: register data migration in sidebar menu and add v1.4.0 changelog"
```

---

## Task 5: 更新 README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README.md 功能列表中新增数据迁移说明**

找到功能列表区域（`## 功能` 或 `## 功能列表` 段落），在"数据库导出"条目后新增：

```markdown
- **数据迁移**：指定多张表从源库迁移到目标库，支持 PostgreSQL / ClickHouse 同构及异构迁移，可选迁移前清空目标表
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README with data migration feature"
```

---

## Task 6: 手工验证

- [ ] **Step 1: 全量语法检查**

```bash
python -m compileall core db gui utils main_gui.py
```

Expected: 所有文件 `Compiling ... ok`，无错误

- [ ] **Step 2: 运行全部自动化测试**

```bash
python -m pytest tests/ -v
```

Expected: 所有测试 PASS

- [ ] **Step 3: 启动 GUI 手工验证**

```bash
python main_gui.py
```

验证清单：
- [ ] 左侧菜单出现 🔁 数据迁移按钮，位于"数据库导出"下方
- [ ] 点击按钮正确加载迁移页面，左右分栏布局正确
- [ ] 页面展示"源数据库连接"和"目标数据库连接"两个下拉选择器
- [ ] 表名输入框可输入多行或逗号分隔
- [ ] "迁移前清空目标表"勾选框默认勾选
- [ ] 欢迎页更新日志显示 v1.4.0 条目
- [ ] 切换到其他页面再返回，迁移页面状态保持（持久化页面）
