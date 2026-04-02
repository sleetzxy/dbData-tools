# 数据迁移功能设计文档

**日期：** 2026-04-02  
**版本：** v1.4.0  
**状态：** 已批准

---

## 1. 功能概述

新增"数据迁移"工具页，允许用户将指定多张表的数据从源数据库迁移到目标数据库。

- 支持同构迁移：PostgreSQL → PostgreSQL、ClickHouse → ClickHouse
- 支持异构迁移：PostgreSQL → ClickHouse、ClickHouse → PostgreSQL
- 目标表需提前在目标库中创建好，工具只负责搬运数据
- 全量迁移（不支持 WHERE 过滤）
- 用户可选择是否在迁移前清空目标表

---

## 2. 技术方案

**中转 CSV 方案（方案 A）**

数据流：

```
源库连接 ──► src_adapter.export_csv() ──► tempfile 临时目录
                                                  │
                                                  ▼
                                         dst_adapter.import_csv() ──► 目标库连接
                                                  │
                                                  ▼
                                            自动清理临时文件
```

复用现有 `PostgreSQLAdapter` 和 `ClickHouseAdapter` 的 `export_csv` / `import_csv` 方法，CSV 作为中间格式天然屏蔽跨库类型差异，无需额外类型映射层。

---

## 3. 新增文件

| 文件路径 | 说明 |
|---|---|
| `core/migrator.py` | 迁移核心逻辑 |
| `gui/pages/database/migrator.py` | 迁移页面（继承 BaseToolPage） |

---

## 4. 修改文件

| 文件路径 | 改动内容 |
|---|---|
| `main_gui.py` | 导入 MigratorPage；在工具按钮列表添加 🔁 按钮；添加 `load_migrator()` 方法；更新 `get_changelog_data()` 新增 v1.4.0 条目 |
| `README.md` | 在功能列表中补充数据迁移说明 |

---

## 5. 核心逻辑（`core/migrator.py`）

### 函数签名

```python
def migrate_tables(
    src_config: dict,
    dst_config: dict,
    table_names: list[str],
    truncate_before: bool,
    logger=None,
) -> dict
```

### 返回格式

```python
{
    "success": bool,
    "migrated_tables": [{"name": str, "rows": int}, ...],
    "error_tables": [{"name": str, "error": str}, ...],
    "total_rows": int,
}
```

### 执行步骤（逐表循环）

1. 创建系统临时目录（`tempfile.mkdtemp()`）
2. 对每张表：
   a. 连接源库，调用 `src_adapter.export_csv()` 将数据写入临时目录
   b. 连接目标库
   c. 若 `truncate_before=True`，执行 TRUNCATE（通过 `import_csv` 的 need_truncate 参数透传，或在 migrator 层直接执行）
   d. 调用 `dst_adapter.import_csv()` 从临时目录导入数据
   e. 删除该表的临时 CSV 文件
   f. 记录成功/失败结果
3. 清理临时目录
4. 返回汇总结果

### 错误处理

- 单表失败不中断整体迁移，继续处理后续表
- 临时文件无论成败都清理
- 最终日志输出成功表数、失败表数、总迁移行数

---

## 6. 页面布局（`gui/pages/database/migrator.py`）

继承 `BaseToolPage`，延续左（配置）右（日志）分栏布局。

### 左侧配置面板（420px）

```
🔁 数据迁移
─────────────────────────────────
源数据库连接        [ConnectionSelector]
─────────────────────────────────
目标数据库连接      [ConnectionSelector]
─────────────────────────────────
迁移的表名（多个用逗号或换行分隔）
┌──────────────────────────────┐
│ table_a                      │
│ table_b, table_c             │
└──────────────────────────────┘
─────────────────────────────────
☑ 迁移前清空目标表（TRUNCATE）
─────────────────────────────────
[🚀 开始迁移]
```

- 源库和目标库使用两个独立的 `ConnectionSelector` 组件
- 允许选同一个连接（支持同库不同 schema 场景）
- 表名输入框使用 `StyledScrolledText`，支持逗号或换行分隔

### 右侧日志面板

标准 `LogPanel`，实时输出：
- 迁移开始信息（源库、目标库、表数量）
- 每张表：开始 → 导出行数 → 导入完成 / 失败原因
- 最终汇总（成功 N 张，失败 M 张，共 X 行）

---

## 7. 菜单注册（`main_gui.py`）

在 `tools_data` 列表中"数据库导出"条目下方插入：

```python
("🔁", "数据迁移", self.load_migrator),
```

新增方法：

```python
def load_migrator(self):
    self._reset_menu_buttons()
    btn = self.command_to_button.get('load_migrator')
    if btn:
        btn.configure(fg_color=self.idea_dark_colors["button_hover"])
    self._show_page('migrator', builder=lambda parent: MigratorPage(parent))
```

---

## 8. 版本更新

### `get_changelog_data()` 新增条目

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

### `README.md` 补充

在功能列表中新增数据迁移工具的说明条目。

---

## 9. 手工验证步骤

1. `python -m compileall core db gui utils main_gui.py` — 检查语法
2. `python main_gui.py` — 启动 GUI，验证：
   - 左侧菜单出现 🔁 数据迁移按钮
   - 点击按钮正确加载迁移页面
   - 选择源库和目标库，输入表名，点击开始迁移
   - 日志实时输出迁移进度
   - "迁移前清空目标表"勾选/不勾选行为正确
   - 单表失败不影响其他表继续迁移
