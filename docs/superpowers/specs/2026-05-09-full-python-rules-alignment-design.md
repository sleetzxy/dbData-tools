# 全仓库 Python 与 Cursor 规则对齐 — 设计规格

**状态：** 已通过人脑确认（brainstorming：范围 A、行为策略 2、路线二、第 1～5 节整体设计）  
**日期：** 2026-05-09  
**关联：** 历史文档 `docs/superpowers/specs/2026-05-08-cursor-rules-refactor-design.md` 描述过工具链与 `src/` 迁移等阶段思路；**本文件**为「在现有 `src/` 布局与 `pyproject.toml` 已存在」前提下，对**全部 Python 源码与测试**按 `.cursor/rules` 全面对齐的权威规格。

---

## 1. 范围与约束

### 1.1 范围（已确认：A）

- **包含：** 仓库内全部 Python，含 `src/`（`core`、`db`、`gui`、`utils`）、`tests/`、`main_gui.py` 及根目录其它 `.py`（若有）。
- **权威规则：** `.cursor/rules/python.mdc`、`.cursor/rules/pytest.mdc`；仓库补充见 `AGENTS.md`，与 `.mdc` 冲突时以 `.mdc` 为准。

### 1.2 行为与重构策略（已确认：2）

- **用户可见功能与主要交互**保持一致；不借机做产品级新功能或更换 UI 框架。
- **允许**为符合规范与可维护性做适度**结构重构**：拆分过大模块、职责下沉（业务进 `core`/`db`/`utils`）、统一异常与常量表达等。
- **禁止**无业务理由改写 SQL 语义、连接默认行为；界面文案与布局非必要不改。

---

## 2. 对齐目标（python.mdc / pytest.mdc 摘要）

### 2.1 代码与模块（python.mdc）

- **格式与布局：** PEP 8；行宽 **88**；import 分组与顺序；命名约定。
- **类型：** 所有函数/方法签名具备参数与返回类型；复杂或歧义变量标注类型；必要时使用 `TYPE_CHECKING` 打破循环依赖。
- **文档字符串：** 公开模块、类、函数使用 **PEP 257**，正文与字段说明采用 **reStructuredText**（Sphinx 兼容）。
- **习惯用法：** 资源用上下文管理器；**避免裸 `except:`** 与无差别宽泛捕获；捕获具体异常；避免可变默认参数；对稳定离散状态优先 `enum.Enum`（不强行枚举化无语义常量堆砌）。
- **提交与协作：** 代码变更的 Git 说明遵循 `.cursor/rules/git-commit-conventions.mdc`（与实现阶段 commit 策略配套）。

### 2.2 测试（pytest.mdc）

- **结构：** `tests/` 作为包；测试文件 `test_*.py`；发现规则与 `pyproject.toml` 中 `pytest` 配置一致。
- **习惯：** 优先 fixture、`pytest-mock`；**新增及本次修改触及的用例**遵循「单断言优先」等团队 pytest 规则。
- **存量测试：** 允许「触达则改、未触达不强拆」以降低无意义 churn；若产品负责人要求**全量**单断言化，须单独立项。

---

## 3. 工具链基线

- **格式化与 Lint：** 在 `pyproject.toml` 的 `dev` 可选依赖中加入 **Ruff**；使用 **ruff format** 与 **ruff check**（兼管 import 顺序），行宽 88，规则集与团队约定在 `[tool.ruff]` 中固化。
- **静态类型：** 继续使用现有 **Pyright** 配置；全仓库收敛后评估是否提高检查严格度。对 **customtkinter** 等缺少精确 stub 的依赖：采用协议封装、局部 `type: ignore`（附简短理由）等，避免散落无理由忽略。
- **可选：** 若团队坚持 Black + isort 与 Ruff 并存，须在 `pyproject.toml` 中明确优先级与 CI/本地命令，避免双工具冲突。**默认推荐** Ruff 一体化以降低维护面。

---

## 4. 实施策略（已确认：路线二 — 分层推进 + 机械基线）

### 4.1 顺序与依赖（自下而上）

1. `src/utils`  
2. `src/db`  
3. `src/core`  
4. `src/gui`  
5. `main_gui.py`  
6. `tests/`

### 4.2 每波完成定义（Definition of Done）

- 该波次相关路径在 **Ruff / Pyright** 下无**未登记**的新违规（登记例外须在规格或 `pyproject` 中可审计）。
- `python -m compileall src/core src/db src/gui src/utils main_gui.py` 通过。
- **`pytest` 全绿**。
- 涉及 `src/gui` 的波次：按 `AGENTS.md` 对关键页面做**手工回归**（连接、CSV 导入/导出/更新、数据库导出、迁移等），并记录简短清单。

### 4.3 Git 策略

- **按主题拆分提交**（例如按子包或按「工具链 / 单模块」），避免单巨型 commit；消息遵循 Angular 风格与仓库「type + 中文描述」习惯，并按需补充 AI 辅助 trailer。

---

## 5. 结构重构边界（在策略 2 内）

**鼓励：**

- 单文件过长或多职责时拆分；页面内复杂逻辑下沉到 `core`/`db`/`utils` 可测函数。
- 用小型异常层次替代泛化 `Exception` 传播；在 GUI 边界统一记录日志与用户提示。
- 与行为强相关的魔法字符串与离散状态，用常量或 `Enum` 表达。

**禁止：**

- 改变业务语义与默认连接行为的「顺手优化」。
- 与规范无关的大规模格式化以外的「洁癖式」重写。

---

## 6. 规格评审说明

- 本仓库未内置 `spec-document-reviewer` 子代理脚本；**评审**由作者自检 + 后续 **plan-document-reviewer**（若可用）或人工 PR 评审补位。
- **人脑闸门：** 实施前须已阅读本规格与对应 **implementation plan**；有异议先改规格/plan 再改代码。

---

## 7. 下游工作

- 实施阶段须先有 **`docs/superpowers/plans/2026-05-09-full-python-rules-alignment.md`**（或其它日期前缀、经人脑同意的计划文件名），再按 plan 分任务执行。
- 执行时推荐 `@superpowers:subagent-driven-development` 或 `@superpowers:executing-plans` 按任务粒度推进（见 plan 文件头说明）。
