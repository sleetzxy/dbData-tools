# 全仓库 Python 与 Cursor 规则对齐 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按下方 checkbox 任务逐步实施并在任务间做简短复核。

**Goal:** 在保持用户可见功能与主交互不变的前提下，使仓库内全部 Python 符合 `.cursor/rules/python.mdc`、`.cursor/rules/pytest.mdc` 与 `AGENTS.md` 中与代码相关的约定，并建立可重复的 Ruff/Pyright 基线。

**Architecture:** 先固化 `pyproject.toml` 中 Ruff 与检查规则，再按依赖自下而上分波修改 `utils` → `db` → `core` → `gui` → `main_gui.py` → `tests`；每波内结合 ruff format/check、Pyright 修复与必要的模块拆分；每波结束运行 `compileall` 与全量 `pytest`，GUI 波次补充手工回归。

**Tech Stack:** Python ≥3.10、setuptools、`pytest`、`pytest-mock`、Ruff、Pyright（Pylance）、`customtkinter`、`psycopg2-binary`、`clickhouse-connect` 等现有运行时依赖。

**规格来源：** `docs/superpowers/specs/2026-05-09-full-python-rules-alignment-design.md`

---

## 文件与职责总览（实施前锁定边界）

| 区域 | 路径模式 | 职责 |
|------|-----------|------|
| 工具与配置 | `pyproject.toml` | dev 依赖、Ruff、Pytest、Pyright |
| 入口 | `main_gui.py` | 薄入口：根窗口、`MainApplication`、日志与致命错误提示 |
| 工具模块 | `src/utils/**/*.py` | 配置、日志工厂等 |
| 数据库 | `src/db/**/*.py` | 连接、适配器、SQL 执行边界 |
| 业务核心 | `src/core/**/*.py` | CSV/DB 导入导出、更新、迁移逻辑 |
| 界面 | `src/gui/**/*.py` | 页面、组件、样式、控件封装 |
| 测试 | `tests/**/*.py`、`tests/conftest.py` | 行为回归与新增规范用例 |

---

### Task 0: 基线与证据

**Files:**

- 只读：全仓库（建立基线）

- [ ] **Step 1: 记录当前测试结果**

在仓库根、已激活且已 `pip install -e ".[dev]"` 的 venv 中执行：

```bash
pytest
```

将退出码与（若失败）失败用例名记入工作笔记或 PR 描述。

- [ ] **Step 2: 语法编译检查**

```bash
python -m compileall src/core src/db src/gui src/utils main_gui.py
```

预期：无错误输出。

- [ ] **Step 3: Commit**

本任务通常不产生代码变更；若有仅文档/笔记，按需提交；否则跳过 commit。

---

### Task 1: 工具链 — 在 pyproject 中引入 Ruff

**Files:**

- Modify: `pyproject.toml`

- [ ] **Step 1: 编辑 `pyproject.toml`**

在 `[project.optional-dependencies]` 的 `dev` 列表中加入 `ruff`（版本与团队锁定策略一致，例如 `ruff>=0.8,<1` 或固定小版本）。

新增 `[tool.ruff]` / `[tool.ruff.lint]` / `[tool.ruff.format]`：

- `line-length = 88`
- `target-version = "py310"`（与 `requires-python` 一致）
- `select`：至少包含 `E`, `F`, `I`, `UP`, `B` 等团队认可集合；`ignore` 仅收录**有书面理由**的项（例如与 Tk 回调相关的极少数规则若需忽略，在注释或本 plan 中说明）
- `src` 与 `tests` 为源根（若需 `extend-exclude` 排除 `build/`、`dist/`）

- [ ] **Step 2: 安装并 dry-run**

```bash
pip install -e ".[dev]"
ruff check . --statistics
ruff format . --check
```

预期：可能大量告警——**本步不要求清零**，只确认命令可运行。

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(dev): add ruff config for rules alignment"
```

---

### Task 2: 全树格式化（可控首次大 diff）

**Files:**

- Modify: 全部将被 `ruff format` 改写的 `.py` 文件

- [ ] **Step 1: 执行 format**

```bash
ruff format .
```

- [ ] **Step 2: 运行测试**

```bash
python -m compileall src/core src/db src/gui src/utils main_gui.py
pytest
```

预期：全部通过。

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "style: apply ruff format across python sources"
```

注意：勿提交 `build/`、`dist/`、`__pycache__/`、`.pytest_cache/` 等（提交前 `git status` 检查）。

---

### Task 3: 波次 A — `src/utils`

**Files:**

- Modify: `src/utils/config_manager.py`
- Modify: `src/utils/log_handler.py`
- Modify: `src/utils/logger_factory.py`
- Modify: `src/utils/__init__.py`

- [ ] **Step 1: 对 utils 运行 ruff check 并逐项修复**

```bash
ruff check src/utils --fix
```

对不可自动修复项：补类型、补公开 API docstring（reST）、收窄 `except`、消除裸 `except:`。

- [ ] **Step 2: Pyright**

在 IDE 或 `pyright` CLI（若配置）下确认 `src/utils` 无新增错误；对第三方缺口使用有注释的 `type: ignore` 或小型 Protocol。

- [ ] **Step 3: 验证**

```bash
python -m compileall src/utils
pytest
```

- [ ] **Step 4: Commit**

```bash
git add src/utils
git commit -m "refactor(utils): align with cursor python rules"
```

---

### Task 4: 波次 B — `src/db`

**Files:**

- Modify: `src/db/__init__.py`
- Modify: `src/db/connection.py`
- Modify: `src/db/adapters/__init__.py`
- Modify: `src/db/adapters/postgresql_adapter.py`
- Modify: `src/db/adapters/clickhouse_adapter.py`

- [ ] **Step 1: ruff check + 手工修复**

```bash
ruff check src/db --fix
```

重点：连接生命周期、适配器接口类型、异常类型层次（可在 `src/db` 增加小型 `exceptions.py` 若当前缺失且有助于消泛化 `Exception`）。

- [ ] **Step 2: 运行定向测试**

```bash
pytest tests/test_connection_config.py tests/test_adapter_dispatch.py -q
pytest
```

- [ ] **Step 3: Commit**

```bash
git add src/db
git commit -m "refactor(db): align with cursor python rules"
```

---

### Task 5: 波次 C — `src/core`

**Files:**

- Modify: `src/core/__init__.py`
- Modify: `src/core/importer_csv.py`
- Modify: `src/core/importer_csv_type.py`
- Modify: `src/core/exporter_csv.py`
- Modify: `src/core/exporter_db.py`
- Modify: `src/core/updater_csv.py`
- Modify: `src/core/migrator.py`

（若拆分出新模块，在本任务内 `git add` 新文件。）

- [ ] **Step 1: 识别「过大或嵌套过深」函数**

将 ZIP 解压等独立逻辑抽到同包内 `_zip_extract.py` 或 `zip_utils.py` 等**单一职责**模块（名称与现有导入风格一致：`from core...`）。

- [ ] **Step 2: ruff + 类型 + docstring + 异常**

对 `raise Exception(...)` 等改为具体异常或包装为 `RuntimeError`/`ValueError` 并保留原日志信息链。

- [ ] **Step 3: 测试**

```bash
pytest tests/test_migrator.py -q
pytest
```

- [ ] **Step 4: Commit**

```bash
git add src/core
git commit -m "refactor(core): align with cursor python rules"
```

---

### Task 6: 波次 D — `src/gui`（含手工回归清单）

**Files:**

- Modify: `src/gui/**/*.py`（按子包分批提交亦可：`base`、`widgets`、`components`、`pages`、`styling`、`app.py`）

- [ ] **Step 1: 分子目录迭代 ruff**

例如：

```bash
ruff check src/gui/base src/gui/widgets --fix
ruff check src/gui/components src/gui/pages --fix
ruff check src/gui/styling src/gui/app.py src/gui/utils --fix
```

对 Tk/CTk 回调：保持签名可被类型检查；必要时使用 `Callable[..., None]` 或包装函数。

- [ ] **Step 2: 手工回归（记录在 PR 或本文件附录）**

最低限度：

1. 启动 `python main_gui.py` 无异常退出。
2. 连接管理页：加载/保存连接配置。
3. CSV 导入、导出、更新页：打开对话框与一次取消或 dry-run（视环境）。
4. 数据库导出、迁移页：打开与依赖连接的 UI 路径。

- [ ] **Step 3: pytest + compileall**

```bash
python -m compileall src/gui
pytest
```

- [ ] **Step 4: Commit（可拆多 commit）**

示例：

```bash
git add src/gui/base src/gui/widgets
git commit -m "refactor(gui): align widgets with cursor rules"
```

---

### Task 7: 波次 E — `main_gui.py`

**Files:**

- Modify: `main_gui.py`

- [ ] **Step 1: 收窄顶层 `except`**

将 `except Exception` 细分为可预期错误类型 + 兜底；`iconbitmap` 失败保留静默或记录 debug 级日志，与规格一致。

- [ ] **Step 2: ruff + Pyright**

```bash
ruff check main_gui.py --fix
```

- [ ] **Step 3: 启动冒烟**

```bash
python main_gui.py
```

短暂打开后关闭窗口，确认无 traceback。

- [ ] **Step 4: Commit**

```bash
git add main_gui.py
git commit -m "refactor(gui): tighten main_gui entry to cursor rules"
```

---

### Task 8: 波次 F — `tests/`

**Files:**

- Modify: `tests/conftest.py`
- Modify: `tests/test_connection_config.py`
- Modify: `tests/test_adapter_dispatch.py`
- Modify: `tests/test_migrator.py`

- [ ] **Step 1: 对测试运行 ruff**

```bash
ruff check tests --fix
```

- [ ] **Step 2: 对「本次改动过的测试函数」应用 pytest.mdc**

补 type hints、fixture 化重复 setup、优先 `mocker.patch` 目标路径为 **`包.模块.名字`** 字符串。

- [ ] **Step 3: pytest**

```bash
pytest
```

- [ ] **Step 4: Commit**

```bash
git add tests
git commit -m "test: align tests with cursor pytest rules"
```

---

### Task 9: Ruff 清零门槛与 Pyright 收紧（可选收官）

**Files:**

- Modify: `pyproject.toml`（若需调整 `select`/`ignore` 以反映最终政策）

- [ ] **Step 1: 全仓库 ruff check 无错误**

```bash
ruff check .
```

若存在必须忽略的目录，写入 `extend-exclude` 并说明原因。

- [ ] **Step 2: Pyright 严格度评估**

若将 `typeCheckingMode` 提升为 `strict`：逐文件消除错误；否则在规格中记录「当前为 basic 及原因」。

- [ ] **Step 3: 最终验证三连**

```bash
python -m compileall src/core src/db src/gui src/utils main_gui.py
ruff check .
pytest
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: finalize ruff/pyright policy for rules alignment"
```

---

## Plan 评审说明

- 若可用 `plan-document-reviewer` 子流程：向其提供本 plan 路径与规格路径 `docs/superpowers/specs/2026-05-09-full-python-rules-alignment-design.md`，按反馈修订（最多 3 轮后升维到人脑）。
- 评审通过后，由执行者选择 **Subagent-Driven** 或 **Inline Execution** 开始改代码。

---

## 执行交接话术（plan 作者完成后向协作者说）

Plan 已保存到 `docs/superpowers/plans/2026-05-09-full-python-rules-alignment.md`。可选执行方式：

1. **Subagent-Driven（推荐）** — 每任务独立子代理 + 任务间复核。  
2. **Inline Execution** — 本会话内按 Task 0→9 批量执行并设检查点。

请选择方式后再动代码。
