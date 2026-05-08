# Cursor 规则对齐与项目重构 — 设计说明

**状态：** 已与人脑确认（brainstorming 全流程第 1～5 节）  
**日期：** 2026-05-08  
**范围：** 工程与 Cursor 规则（`.cursor/rules`）对齐 + 代码结构改进；**不**包含业务功能扩展或更换 UI 框架。

---

## 1. 背景与目标

### 1.1 背景

- 仓库为基于 Tkinter 的 PostgreSQL 数据工具桌面应用（见 `AGENTS.md`）。
- `.cursor/rules` 中的 `python.mdc`、`pytest.mdc` 要求：`pyproject.toml`、`src/` 布局、类型标注、pytest 针对已安装包等；与当前「根目录扁平包、无 `pyproject.toml`」存在差距。
- `main_gui.py` 体量较大，与 AGENTS 中「不要把实现细节持续堆回入口」存在张力。

### 1.2 目标

- 与团队 Cursor 规则及 `AGENTS.md` 可对齐：**工具链、布局、测试、文档**可重复执行。
- 提升可维护性：**入口职责清晰**，业务逻辑保持在 `core/`、`db/`、`utils/`。

### 1.3 非目标

- 不改变现有 Tkinter 交互与功能行为（除非为修 bug 或满足工具链所必需）。
- 不借机做大功能迭代或更换 UI 框架。
- M3 不要求全量 GUI 自动化测试。

---

## 2. 总体策略：三阶段（M1 → M2 → M3）

| 阶段 | 主题 | 核心动作 |
|------|------|----------|
| **M1** | 工具链 + 文档 | `pyproject.toml`、pytest/Ruff/Black（按约定范围）、依赖单轨、明显笔误清理；**不**迁移 `src/` |
| **M2** | `src/` 与安装/测试/打包 | 将 `core/`、`db/`、`gui/`、`utils/` 迁入 `src/`；可编辑安装；pytest/PyInstaller/README 同步 |
| **M3** | 瘦入口 + 类型 + 测试 | 拆分 `main_gui.py`；渐进类型标注与测试补强 |

**分阶段理由：** M1 快速建立可重复验证；M2 集中处理布局与导入的一次性迁移；M3 在稳定包边界上做结构与类型，避免在巨型入口文件中同时完成 `src/` 迁移。

---

## 3. M1：工具链与文档（保持根下包布局）

### 3.1 交付物

1. **`pyproject.toml`（PEP 621）**  
   - 项目元数据、Python 版本下限与当前环境一致。  
   - **运行时依赖**：以代码真实 import 为准；若存在 `requirements.txt`，在 M1 **合并进 pyproject 或明确弃用其一**，避免双轨。  
   - **开发依赖**：至少 `pytest`；可选 `ruff`、`black`、`pytest-cov`、`pytest-mock`。  
   - **`[tool.pytest.ini_options]`**：`testpaths = tests`，配置使在仓库根执行 `pytest` 一键可跑（仍为扁平包）。  
   - **`[tool.ruff]` / `[tool.black]`**：行宽等与团队一致；Ruff 可先放宽，避免 M1 被海量告警阻塞。

2. **小清理**  
   - 例如 `main_gui.py` 中重复的 `MigratorPage` 导入等无行为变更修复。

3. **文档**  
   - `README.md` / `AGENTS.md`：venv、`pip install -e .`（或 Poetry 等价）、`pytest`、Ruff/Black（若启用）的说明。  
   - **主路径**仍保留 `python main_gui.py` 启动说明。

### 3.2 验收

- 干净 venv：`pip install -e ".[dev]"`（或文档等价步骤）后 **`pytest` 全绿**。  
- `python -m compileall …` 通过。  
- `python main_gui.py` 可启动（手工）。  
- 若启用 Ruff/Black：文档或 CI 中定义 **当前必过范围**，且仓库在该范围内通过或附有明确「已知待办」清单。

---

## 4. M2：`src/` 布局、安装、测试与打包

### 4.1 目录约定

```
src/
  core/
  db/
  gui/
  utils/
```

- **保留四个顶层包名**：`core`、`db`、`gui`、`utils`（与现有 `from gui...` 等一致），**不**在 M2 引入新的统一命名空间前缀（如 `dbdata_tools.gui`），以降低 import 改写面。  
- 构建：`pyproject.toml` 中 setuptools（或选定后端）从 `src/` 发现包。

### 4.2 入口 `main_gui.py`

- **默认**：`main_gui.py` **保留在仓库根**；正常运行前提为文档化：**先 `pip install -e .`**，再 `python main_gui.py`。  
- **不**以 `sys.path.insert(0, "src")` 作为主要方案。零安装脚本若需支持，单独附录评估，**非 M2 必交付**。

### 4.3 测试

- 在已可编辑安装的 venv 中 `pytest` 全绿；去掉对「必须把仓库根当作唯一 `PYTHONPATH`」的隐式依赖（与 M1 的 pytest 配置协调）。

### 4.4 PyInstaller

- 更新 `README.md` / `AGENTS.md`：工作目录、入口路径、必要时 `--paths` 或等价参数。  
- M2 验收：**按文档执行一次**可打出可运行产物（或与 CI 对齐的一键命令）。

### 4.5 验收

- 根目录下 **无**业务包源码副本（仅 `src/` 下保留 `core`、`db`、`gui`、`utils`）。  
- `pip install -e .` 后：`pytest` 全绿；`python main_gui.py` 可启动。  
- `compileall` 路径/命令已更新覆盖 `src/` 与根入口。  
- PyInstaller 文档与一次本地验证完成。

---

## 5. M3：瘦入口、类型与测试

### 5.1 入口拆分（建议顺序）

1. **`ToolTipManager` 及强相关纯 UI 辅助** → `gui/widgets/` 或 `gui/components/`（文件名与现有风格对齐）。  
2. **主窗口 / 侧栏 / 页面路由** → 抽至 `gui/` 下模块或小型类（如 `MainApplication` / `ShellWindow`），仍为 Tkinter。

### 5.2 类型标注

- **优先**：`core/`、`db/` 对外 API、适配器边界、迁移/导入导出关键路径。  
- **其次**：`gui/pages/` 中与业务边界清晰的部分。  
- **mypy**：可用 `files` 白名单渐进扩大，避免全仓库一次爆量。

### 5.3 测试

- 对抽出后的 **纯函数 / 易 mock** 逻辑补 `tests/test_*.py`。  
- 强依赖 Tk 的部分以手工回归为主。

### 5.4 验收

- `main_gui.py` 相对 M2 **行数与职责明显收敛**（实现计划中可量化里程碑，如 Tooltip 与主壳分离为硬标准）。  
- `pytest` 全绿；`compileall` 覆盖更新路径。  
- 文档中开发流程与检查命令与工具链一致。

---

## 6. 错误处理、回归与风险

### 6.1 错误处理

- 重构 **不改变**用户可见错误语义与主要异常分支，除非修复明确 bug。  
- 移动代码时 **不**无故扩大 `except` 范围（避免吞掉 `KeyboardInterrupt` 等）。

### 6.2 回归（每阶段结束）

- `compileall` → `pytest` → `python main_gui.py` 关键路径手工点验（按改动面选最小集）。  
- **M2 后**必须增加一次按文档的 PyInstaller 验证。

### 6.3 风险与缓解

| 风险 | 缓解 |
|------|------|
| `src/` 迁移漏路径 | 可编辑安装 + 全量 pytest + 一次打包验证 |
| Windows 路径与编码 | 不借机改 CSV 编码等既有策略 |
| 文档与本地习惯不一致 | 以本 spec + `.cursor/rules` 为准，同步改 `AGENTS.md` / `README.md` |

---

## 7. 与仓库文档的关系

实施时若 `AGENTS.md` 与本 spec 或 `.cursor/rules` 冲突，以 **本 spec 与 `.cursor/rules`** 为实施依据，并 **更新 AGENTS/README** 消除歧义。

---

## 8. 后续工作流

1. 本文件通过 spec 文档评审后，由维护者过目确认。  
2. 使用 **writing-plans** 技能生成 `docs/superpowers/plans/2026-05-08-cursor-rules-refactor.md`（或同主题实现计划）。  
3. 按任务拆分实现，每阶段独立可合并、可验证。
