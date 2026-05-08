# Cursor 规则对齐与项目重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `.cursor/rules` 与 `AGENTS.md` 对齐项目工程化（pyproject + 测试/检查工具链）、迁移至 `src/` 布局，并瘦身 `main_gui.py`。

**Architecture:** 三阶段递进：**M1** 在保持当前根目录扁平包的前提下引入 `pyproject.toml`、统一 pytest 入口、清理小问题、补文档；**M2** 将 `core/`、`db/`、`gui/`、`utils/` 迁入 `src/<同名包>`，可编辑安装、pytest 与 PyInstaller 同步；**M3** 把 `main_gui.py` 中 `ToolTipManager` 与主壳拆出去，并对 `core/`、`db/` 关键路径渐进补类型与测试。包名 (`core`/`db`/`gui`/`utils`) 全程不变以最小化 import 改动。

**Tech Stack:** Python 3、Tkinter / customtkinter、psycopg2-binary、clickhouse-connect、pyzipper、pypinyin、pytest（可选 ruff/black/mypy/pytest-cov/pytest-mock）、setuptools（PEP 621 via `pyproject.toml`）、PyInstaller。

**参考 Spec:** `docs/superpowers/specs/2026-05-08-cursor-rules-refactor-design.md`

---

## 总体注意事项

- **每个 Task 都以 commit 收尾**，遵循 `git-commit-conventions.mdc`：`type: 中文描述`，必要时 Body 写动机；可在 Body 末加 `AI-Assisted-by: Cursor`、`Co-authored-by: <Author>`。
- **不要无故扩大 try/except**；不修改用户可见错误语义（除非修明确 bug）。
- **每完成一个 Task** 后跑：
  - `python -m compileall core db gui utils main_gui.py`（M2 起改为覆盖 `src/` 与根入口）
  - `pytest`
  - 若涉及 GUI 路径，启动 `python main_gui.py` 手工点验。
- **M2 起**所有「编辑安装」操作都假设你已 `python -m venv .venv` 并激活；命令示例在 PowerShell 下书写。
- **每个 Task 内的 Step 是 2~5 分钟级动作**；TDD 在适用范围内（纯 Python 逻辑）使用，GUI 部分以手工回归为主。

---

## 文件结构总览

| 阶段 | 创建 / 修改 | 说明 |
|------|-------------|------|
| M1 | 新建 `pyproject.toml` | PEP 621 项目元数据、依赖、pytest/Ruff/Black 配置 |
| M1 | 新建 `tests/conftest.py` | 让 pytest 在「未安装包」时也能在仓库根运行（M2 后冗余将被删） |
| M1 | 修 `main_gui.py` | 删除重复 `MigratorPage` 导入 |
| M1 | 修 `tests/test_migrator.py`、`tests/test_adapter_dispatch.py` | 删 `sys.path.insert` 兜底（改由 conftest 或可编辑安装提供） |
| M1 | 修 `README.md`、`AGENTS.md` | 加入 venv / `pip install -e .` / pytest / ruff 说明 |
| M1（可选） | 是否启用 Ruff/Black/mypy 由维护者勾选；本计划中作为可选 Task 标识 |
| M2 | 移动 `core/` → `src/core/`、`db/` → `src/db/`、`gui/` → `src/gui/`、`utils/` → `src/utils/` | 包名不变，仅根目录改变 |
| M2 | 修 `pyproject.toml` | `tool.setuptools.packages.find` 改用 `where = ["src"]` |
| M2 | 删除 `tests/conftest.py`（或瘦身） | 由可编辑安装提供导入路径 |
| M2 | 修 `README.md` / `AGENTS.md` | 更新 compileall、PyInstaller、运行说明 |
| M3 | 新建 `src/gui/widgets/tooltip.py` | 从 `main_gui.py` 抽出 `ToolTipManager` |
| M3 | 新建 `src/gui/app.py`（或 `shell.py`） | 抽出 `MainApplication` |
| M3 | 改 `main_gui.py` | 仅保留入口装配（创建 root、实例化主壳、`mainloop`） |
| M3（可选） | 选择性补 `tests/test_*.py`、`mypy.ini` | 渐进类型与覆盖率 |

---

# M1：工具链与文档（不迁 src/）

### Task M1-1：新建 `pyproject.toml`（PEP 621 + setuptools 后端，根目录包发现）

**Files:**
- Create: `pyproject.toml`

**Why:** `.cursor/rules/python.mdc` 要求项目以 `pyproject.toml` 描述元数据与构建。当前仓库无该文件。本 Task 在保持「根下扁平包」前提下完成最小可用配置；M2 会把 `packages` 配置切到 `src/`。

- [ ] **Step 1：在仓库根创建 `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "dbdata-tools"
version = "1.4.0"
description = "基于 Tkinter 的 PostgreSQL 数据工具桌面应用"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
  "customtkinter==5.2.2",
  "psycopg2-binary==2.9.11",
  "pypinyin==0.55.0",
  "pyzipper==0.3.6",
  "clickhouse-connect==0.8.18",
]

[project.optional-dependencies]
dev = [
  "pytest==9.0.2",
  "pytest-mock>=3.12",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["core*", "db*", "gui*", "utils*"]
exclude = ["tests*", "build*", "dist*", "docs*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2：与 `requirements.txt` 对齐（明确以 `pyproject.toml` 为权威）**

逐条核对包名与版本，规则：**以 `pyproject.toml` 为权威源**。若发现差异，**改 `requirements.txt`** 与 pyproject 一致，**不要**反向修改 pyproject。

应对齐的包清单（与当前 `requirements.txt` 一致）：

- `customtkinter==5.2.2`
- `psycopg2-binary==2.9.11`
- `pypinyin==0.55.0`
- `pyzipper==0.3.6`
- `clickhouse-connect==0.8.18`
- `pytest==9.0.2`（dev）

核对命令：

```powershell
Get-Content requirements.txt
Select-String -Path pyproject.toml -Pattern "customtkinter|psycopg2|pypinyin|pyzipper|clickhouse-connect|pytest"
```

期望：两侧版本号一一对应；若不一致则只改 `requirements.txt`。

保留 `requirements.txt` 一段时间（避免外部脚本依赖中断），并在 README 顶部加一句「**依赖权威来源为 `pyproject.toml`，`requirements.txt` 仅为镜像，过渡期保留**」。

- [ ] **Step 3：本地干跑验证**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
```

期望：安装成功，`pip show dbdata-tools` 能查到版本 1.4.0。

- [ ] **Step 4：commit**

```powershell
git add pyproject.toml
git commit -m "chore: 引入 pyproject.toml 描述项目元数据与依赖"
```

---

### Task M1-2：新建 `tests/conftest.py` 让无安装也能跑测试

**Files:**
- Create: `tests/conftest.py`

**Why:** 现有 `tests/test_migrator.py`、`tests/test_adapter_dispatch.py` 在文件内 `sys.path.insert(...)`。统一改用 `conftest.py` 把仓库根加进 `sys.path`，让 M1 阶段无论是否 `pip install -e .` 都能跑 `pytest`；M2 切换到 `src/` 后此文件可被精简或删除。

- [ ] **Step 1：写 `tests/conftest.py`**

```python
"""Pytest 共享 fixture 与测试发现配置。

M1 阶段仓库仍为根下扁平包结构。本文件把仓库根加入 sys.path，
让 `pytest` 在未执行可编辑安装时也能解析 `core`/`db`/`gui`/`utils` 包。
M2 迁移到 `src/` 布局并以可编辑安装运行后，本文件可被精简或删除。
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
```

- [ ] **Step 2：运行 pytest 验证**

```powershell
pytest -q
```

期望：`tests/test_connection_config.py`、`tests/test_migrator.py`、`tests/test_adapter_dispatch.py` 全绿（与现状一致）。

- [ ] **Step 3：commit**

```powershell
git add tests/conftest.py
git commit -m "test: 用 conftest.py 统一测试导入路径"
```

---

### Task M1-3：清理测试中的 `sys.path.insert` 兜底

**Files:**
- Modify: `tests/test_migrator.py`（前几行的 `sys.path.insert` 块）
- Modify: `tests/test_adapter_dispatch.py`（前几行的 `sys.path.insert` 块）

**Why:** Task M1-2 已在 `conftest.py` 集中处理；测试文件里再写 `sys.path.insert` 是重复且与规则不一致。

- [ ] **Step 1：修改 `tests/test_migrator.py`**

删除：
```python
import sys
...
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
```

仅保留必要的 `import os`、`import tempfile`、`import shutil`、`import pytest` 及业务 import。

- [ ] **Step 2：修改 `tests/test_adapter_dispatch.py`**

删除同样形式的 `sys.path.insert(...)` 与不再需要的 `import sys`。

- [ ] **Step 3：跑测试**

```powershell
pytest -q
```

期望：全绿。

- [ ] **Step 4：commit**

```powershell
git add tests/test_migrator.py tests/test_adapter_dispatch.py
git commit -m "refactor: 移除测试文件中的 sys.path 兜底"
```

---

### Task M1-4：修复 `main_gui.py` 重复导入

**Files:**
- Modify: `main_gui.py`（第 10–11 行）

**Why:** 当前两次 `from gui.pages.database.migrator import MigratorPage`，纯笔误，归入 M1 小清理。

- [ ] **Step 1：删除重复行**

把：
```python
from gui.pages.database.migrator import MigratorPage
from gui.pages.database.migrator import MigratorPage
```
改为单行：
```python
from gui.pages.database.migrator import MigratorPage
```

- [ ] **Step 2：语法检查与启动验证**

```powershell
python -m compileall core db gui utils main_gui.py
python main_gui.py
```

期望：`compileall` 0 errors；GUI 正常启动并能切到「数据迁移」页面。手工关闭即可。

- [ ] **Step 3：commit**

```powershell
git add main_gui.py
git commit -m "fix: 移除 main_gui 中重复的 MigratorPage 导入"
```

---

### Task M1-5（可选）：接入 Ruff + Black 的「可过子集」

**Files:**
- Modify: `pyproject.toml`（追加 `[tool.ruff]`、`[tool.black]` 与 dev 依赖）
- Modify: `README.md` / `AGENTS.md`（可选，写入命令）

**Why:** `.cursor/rules/python.mdc` 推荐 Ruff/Black。但仓库现状若全开会有大量历史告警，本 Task 只接入「可全仓库立即通过」的最小子集，留待后续 PR 渐进收紧。

- [ ] **Step 1：在 `pyproject.toml` 增加配置（行宽 88，Ruff 仅启用 E9/F63/F7/F82 等运行期级别规则）**

```toml
[project.optional-dependencies]
dev = [
  "pytest==9.0.2",
  "pytest-mock>=3.12",
  "ruff>=0.5",
  "black>=24.0",
]

[tool.black]
line-length = 88
target-version = ["py310"]

[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = ["E9", "F63", "F7", "F82"]
```

- [ ] **Step 2：本地验证**

```powershell
pip install -e ".[dev]"
ruff check .
```

期望：`ruff check .` 0 errors。`black --check .` 可作为信息性指标，**本 Task 不要求 0 diff**；若维护者希望同步 Black 全仓格式化，作为单独提交（一次性 reformat），不要混入功能 PR。

- [ ] **Step 3：在 README/AGENTS 增加一节「代码检查」**

```markdown
## 代码检查（可选）
pip install -e ".[dev]"
ruff check .
black --check .   # 不强制 0 diff，建议新文件遵循
```

- [ ] **Step 4：commit**

```powershell
git add pyproject.toml README.md AGENTS.md
git commit -m "chore: 接入 Ruff/Black 最小可过子集"
```

---

### Task M1-6：在 README/AGENTS 写入「环境与运行」

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

**Why:** Spec §3.1 要求文档化 venv、`pip install -e .`、pytest、可选 ruff 等命令。

- [ ] **Step 1a：在 `README.md` 中追加「快速开始」小节**

要写入 README 的实际 Markdown 内容（请逐字粘贴，自行加节标题前的空行）：

  - 标题：`## 快速开始`
  - 紧随其后是一个 `powershell` 围栏代码块，内容如下（注意：在 README 里要写真实的三反引号；这里用四反引号外层包裹，避免本计划文档自身渲染断裂）：

````markdown
## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
python main_gui.py
```
````

- [ ] **Step 1b：在 `README.md` 中追加「测试与检查」小节**

````markdown
## 测试与检查

```powershell
pytest
python -m compileall core db gui utils main_gui.py
```
````

> 注：M2 完成后，`compileall` 命令会变为 `python -m compileall src/core src/db src/gui src/utils main_gui.py`（见 Task M2-4）。M1 阶段保持上面的写法即可。

- [ ] **Step 2：在 `AGENTS.md` 的「常用命令」一节增加「准备环境」一条，并把「运行测试」更新为依赖于 `pip install -e ".[dev]"` 的版本。**

- [ ] **Step 3：commit**

```powershell
git add README.md AGENTS.md
git commit -m "docs: 补充 venv 与可编辑安装的运行说明"
```

---

### M1 验收

- 干净 venv 中：`pip install -e ".[dev]"` 后 **`pytest` 全绿**。
- `python -m compileall core db gui utils main_gui.py` 通过。
- `python main_gui.py` 可启动主界面（手工点验）。
- 若 Task M1-5 启用：`ruff check .` 通过。

---

# M2：迁移到 `src/` 布局

> **重点提醒：** M2 是结构性变更，**单独一个分支/PR**，所有 Task 之间紧密相关。建议按 Task 顺序连续完成，**不要中途穿插 M3**。

### Task M2-1：物理迁移 `core/`、`db/`、`gui/`、`utils/` 到 `src/`

**Files:**
- Move: `core/` → `src/core/`
- Move: `db/` → `src/db/`
- Move: `gui/` → `src/gui/`
- Move: `utils/` → `src/utils/`

**Why:** Spec §4.1 约定的 `src/` 布局。包名不变，只换根目录位置。

- [ ] **Step 1：用 `git mv` 执行迁移，保留历史**

```powershell
mkdir src
git mv core src/core
git mv db src/db
git mv gui src/gui
git mv utils src/utils
git status
```

期望：`git status` 显示 4 个 `renamed:` 操作。

- [ ] **Step 2：暂不 commit（结构变更与配置变更一起 commit）**

---

### Task M2-2：更新 `pyproject.toml` 包发现到 `src/`

**Files:**
- Modify: `pyproject.toml`（`[tool.setuptools.packages.find]` 段）

- [ ] **Step 1：修改包发现配置**

把：
```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["core*", "db*", "gui*", "utils*"]
exclude = ["tests*", "build*", "dist*", "docs*"]
```
改为：
```toml
[tool.setuptools.packages.find]
where = ["src"]
include = ["core*", "db*", "gui*", "utils*"]
```

- [ ] **Step 2：重新可编辑安装并验证**

```powershell
pip install -e ".[dev]"
python -c "import core, db, gui, utils; print('ok')"
```

期望：输出 `ok`。

---

### Task M2-3：清理 `tests/conftest.py` 与残留 `sys.path` 兜底

**Files:**
- Modify: `tests/conftest.py`（精简或删除）

**Why:** 包已可通过可编辑安装解析，conftest 中的 `sys.path` 注入不再必要。

- [ ] **Step 1：把 `tests/conftest.py` 改为一个简单的占位**

```python
"""Pytest 配置占位。

包通过 `pip install -e .` 注册到当前虚拟环境，
不再需要 sys.path 兜底。本文件保留以便后续放置共享 fixture。
"""
```

或直接 `git rm tests/conftest.py`（二选一，团队偏好可在执行时确定）。

- [ ] **Step 2：跑测试**

```powershell
pytest -q
```

期望：全绿。若 ImportError，多半是仍有文件用「相对仓库根」的隐式路径访问数据；按报错修。

---

### Task M2-4：搜索并修正剩余的旧路径引用（文档/脚本）

**Files:**
- Modify: 任何包含 `from core` / `from db` / `from gui` / `from utils` 之外的 **路径式** 引用的 `.md` / `.spec` / 脚本文件。

**Why:** 包名未改，**Python import 语句应保持不变**；但 `compileall`、PyInstaller、README 中可能用「目录路径」写法，需要更新到 `src/`。

- [ ] **Step 1：用 ripgrep 搜索旧路径**

```powershell
rg -n "compileall .*core .*db .*gui .*utils" -S
rg -n "(\\b|/)core/(\\b|/)" -S --glob "!src/**" --glob "!.git/**"
```

把 `python -m compileall core db gui utils main_gui.py` 改为：
```
python -m compileall src/core src/db src/gui src/utils main_gui.py
```

- [ ] **Step 2：检查 PyInstaller 命令**

`AGENTS.md` 中：
```
pyinstaller --clean --onefile --windowed --uac-admin --name "DB数据工具集" .\main_gui.py
```
保留入口相同；但若 `--paths` 缺省导致打包遗漏 `src/`，添加：
```
--paths src
```

最终命令示例：
```
pyinstaller --clean --onefile --windowed --uac-admin --paths src --name "DB数据工具集" .\main_gui.py
```

更新 `AGENTS.md` 与 `README.md` 中的两处。

- [ ] **Step 3：跑 compileall 验证新路径**

```powershell
python -m compileall src/core src/db src/gui src/utils main_gui.py
```

期望：0 errors。

---

### Task M2-5：M2 整体提交

**Files:**
- 包含 Task M2-1 ~ M2-4 的全部更改

- [ ] **Step 1：跑全套验证**

```powershell
pip install -e ".[dev]"
python -m compileall src/core src/db src/gui src/utils main_gui.py
pytest -q
python main_gui.py   # 手工点验：连接管理、CSV 导入/导出、迁移页面均能打开
```

- [ ] **Step 2：commit**

```powershell
git add -A
git commit -m "refactor: 迁移业务包到 src/ 布局并对齐工具链

- core/db/gui/utils 全部移入 src/，包名保持不变
- pyproject 切到 src 包发现，pytest 不再依赖 sys.path 兜底
- compileall/PyInstaller 命令同步更新到 src/

AI-Assisted-by: Cursor"
```

- [ ] **Step 3：本地一次 PyInstaller 验证**

```powershell
pyinstaller --clean --onefile --windowed --uac-admin --paths src --name "DB数据工具集" .\main_gui.py
.\dist\DB数据工具集.exe
```

期望：可启动并切换到任一页面。打包产物不入库（`.gitignore` 已忽略 `dist/`、`build/`）。

> 若 PyInstaller 报缺隐式导入（如 `customtkinter` 资源），优先用 `--collect-all customtkinter` 或在 `.spec` 中加 `hiddenimports`，**作为单独一个 commit**，与 M2 主提交分开。

---

### M2 验收

- 仓库根下不再有 `core/`、`db/`、`gui/`、`utils/`（仅 `src/` 下保留）。
- `pip install -e .` 后 `pytest` 全绿，`python main_gui.py` 可启动。
- `compileall` 命令覆盖 `src/` 与根入口，文档同步更新。
- 一次本地 PyInstaller 打包可运行。

---

# M3：瘦入口、类型与测试

### Task M3-1：抽出 `ToolTipManager` 到 `src/gui/widgets/tooltip.py`

**Files:**
- Create: `src/gui/widgets/tooltip.py`
- Modify: `main_gui.py`（删除内嵌 class，改为 import）

**Why:** Spec §5.1 要求把 `ToolTipManager`（`main_gui.py` 第 21–202 行附近）迁到 `gui/widgets`。该类是纯 UI 工具，无业务依赖，移动风险低。

- [ ] **Step 1：创建新文件 `src/gui/widgets/tooltip.py`**

把 `main_gui.py` 中 `class ToolTipManager` 完整搬过去；模块顶部仅保留必要 import：
```python
import tkinter as tk
from typing import Optional
```
不引入新依赖；不修改方法签名。

- [ ] **Step 2：在 `main_gui.py` 删除原 class 并改为 import**

把：
```python
class ToolTipManager:
    ...
```
删除，改为：
```python
from gui.widgets.tooltip import ToolTipManager
```
（与现有 `from gui.widgets.* import *` 风格一致。）

- [ ] **Step 3：编译与启动验证**

```powershell
python -m compileall src/core src/db src/gui src/utils main_gui.py
python main_gui.py
```

期望：界面正常，鼠标停留在按钮 100ms 后出现工具提示，点击按钮后 tooltip 隐藏并抑制。**这是手工回归点**。

- [ ] **Step 4：commit**

```powershell
git add src/gui/widgets/tooltip.py main_gui.py
git commit -m "refactor: 抽出 ToolTipManager 到 gui.widgets.tooltip"
```

---

### Task M3-2：抽出 `MainApplication` 到 `src/gui/app.py`

**Files:**
- Create: `src/gui/app.py`
- Modify: `main_gui.py`（保留入口；class 主体迁出）

**Why:** `main_gui.py` 第 203 行起的 `MainApplication` 是主壳，包含菜单/侧栏/页面装配。Spec §5.1 要求 `main_gui.py` 仅保留启动入口。

- [ ] **Step 1：创建 `src/gui/app.py`，把 `MainApplication` 类整体搬过去**

模块顶部保留它需要的 import（基本就是当前 `main_gui.py` 顶部那批 `from gui.pages...`、`from gui.styling...`、以及 `from gui.widgets.tooltip import ToolTipManager`）。

- [ ] **Step 2：将 `main_gui.py` 改造为薄入口**

最终 `main_gui.py` 内容仅保留：
```python
"""桌面应用入口。

仅负责创建根窗口、实例化主壳并进入事件循环。
具体页面装配与 tooltip 等实现位于 gui.app / gui.widgets.tooltip。
"""
from __future__ import annotations

import logging
import tkinter as tk

from gui.app import MainApplication

logging.basicConfig(level=logging.INFO)


def main() -> None:
    root = tk.Tk()
    MainApplication(root)
    root.mainloop()


if __name__ == "__main__":
    main()
```

> 若 `MainApplication.__init__` 当前需要的不只是 `root`（例如还需要 logger 或配置），请按它实际签名调用，**不要在本 Task 改它的签名**。签名调整作为独立 Task。

- [ ] **Step 3：编译与启动验证**

```powershell
python -m compileall src/core src/db src/gui src/utils main_gui.py
python main_gui.py
```

期望：与拆分前完全一致的启动效果（侧栏、各页面、迁移页面、连接管理）。**这是手工回归密集点**：每个一级菜单都点一次。

- [ ] **Step 4：commit**

```powershell
git add src/gui/app.py main_gui.py
git commit -m "refactor: 抽出 MainApplication 到 gui.app，瘦化入口"
```

---

### Task M3-3（可选）：核心模块类型补强（`core/migrator.py`、`core/importer_csv.py`、`db/connection.py`）

**Files:**
- Modify: `src/core/migrator.py`
- Modify: `src/core/importer_csv.py`
- Modify: `src/db/connection.py`

**Why:** Spec §5.2 优先在 `core/`、`db/` 对外 API 补全类型；这些是数据正确性敏感路径。已有 `from __future__ import annotations` 与 `typing` 导入，补全成本低。

- [ ] **Step 1：对每个文件的 **公开函数** 补 `-> ReturnType`、参数注解**

不要扩大重构范围；不要改函数体逻辑。逐个文件 commit。

- [ ] **Step 2：每修一个文件后跑一次** `pytest -q` **保证回归。**

- [ ] **Step 3（可选）：引入 mypy 白名单**

新建 `pyproject.toml` 中：
```toml
[tool.mypy]
python_version = "3.10"
files = ["src/core/migrator.py", "src/core/importer_csv.py", "src/db/connection.py"]
ignore_missing_imports = true
```
跑：
```powershell
pip install mypy
mypy
```
期望：0 error 或仅剩可控的 `# type: ignore` 场景。

- [ ] **Step 4：commit（每个被加注的文件一条）**

例如：
```powershell
git add src/core/migrator.py
git commit -m "refactor: 补全 core.migrator 的类型注解"
```

---

### Task M3-4（可选）：补 1~2 个易测纯函数的单元测试

**Files:**
- Create: `tests/test_<module>.py`（按你想覆盖的纯函数选择）

**Why:** Spec §5.3，针对从 `main_gui` 抽出后或 `core/` 中现存的 **无 Tk 依赖** 函数（如 `core/importer_csv.generate_copy_commands` 之类）补 TDD 风格测试。

- [ ] **Step 1：先写一个失败用例**（按 `pytest.mdc` 推荐：单一断言 / 参数化 / fixture）。
- [ ] **Step 2：跑 pytest 确认 RED。**
- [ ] **Step 3：若是补测试覆盖既有逻辑，把断言调到与现状一致；若是发现 bug，先记 issue 再决定是否在本 PR 内修。**
- [ ] **Step 4：跑 pytest 确认 GREEN，commit。**

```powershell
git add tests/test_<module>.py
git commit -m "test: 补充 <module> 的纯函数用例"
```

---

### Task M3-5：M3 收尾文档更新

**Files:**
- Modify: `AGENTS.md`（如需更新「目录结构」一节，体现 `src/gui/widgets/tooltip.py`、`src/gui/app.py`）
- Modify: `README.md`（如需更新「项目结构」段落）

- [ ] **Step 1：让 `AGENTS.md` 与现状一致：`gui/widgets/` 含 `tooltip.py`；`gui/` 下新增 `app.py`（主壳）。**
- [ ] **Step 2：commit**

```powershell
git add AGENTS.md README.md
git commit -m "docs: 同步 main_gui 拆分后的目录说明"
```

---

### M3 验收

- `main_gui.py` 行数大幅收敛（目标 ≤ 50 行；硬指标：**不再包含** `class ToolTipManager` 与 `class MainApplication` 主体）。
- `pytest` 全绿；`compileall` 通过。
- 文档与现状一致。
- 关键页面（CSV 导入 / 导出 / 更新 / 数据库导出 / 迁移 / 连接管理）手工点验通过。

---

## 阶段间合并策略

- **每个 M（M1/M2/M3）作为一个独立 PR**；M2 因结构变更建议 squash 后单独合并。
- **Task M1-5（Ruff/Black）** 与 **Task M3-3（类型）/ M3-4（测试）** 标为可选；维护者可在三阶段中选择是否纳入对应 PR；不影响主路径验收。
- 合并到 `main` 前必须满足：`pytest` 全绿、`compileall` 通过、`python main_gui.py` 启动正常。

## 风险与回滚

- M2 是高风险阶段。若合并后发现某页面无法导入：
  - **首选**：补 `pyproject.toml` 中 `tool.setuptools.packages.find.include` 或检查包内是否漏了 `__init__.py`。
  - **次选**：单 PR 回滚 M2 commit，回到 M1 状态，下次重做。
- M3-2（拆 `MainApplication`）若手工回归发现某页面打不开，回滚该 Task 即可，不影响 M3-1 与 M2 收益。
