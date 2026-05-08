# Repository Guidelines

## 项目概览
这是一个基于 Tkinter 的 PostgreSQL 数据工具桌面应用，主要面向日常的数据导入、导出、更新与迁移场景。默认入口文件是 `main_gui.py`。改动时优先保持现有交互方式、页面组织和桌面端使用习惯的一致性。

## 规范来源（AGENTS 与 Cursor Rules 的关系）
本仓库有两层规范，**两层都要遵守**：

1. **`.cursor/rules/*.mdc`（团队通用规范，权威）** — 由 Cursor 自动注入对应文件类型，**任何冲突以这里为准**：
   - [`.cursor/rules/python.mdc`](.cursor/rules/python.mdc)：Python 代码风格、类型标注、PEP 8、`src/` 布局、依赖与测试管理等。
   - [`.cursor/rules/pytest.mdc`](.cursor/rules/pytest.mdc)：pytest 项目结构、命名、fixture、mock、覆盖率等。
   - [`.cursor/rules/git-commit-conventions.mdc`](.cursor/rules/git-commit-conventions.mdc)：Angular 风格 commit message、AI 辅助标注、合并策略等。
2. **`AGENTS.md`（本文件，仓库专属补充）** — 仅记录本仓库的目录结构、命令、流程与术语等无法在通用 .mdc 里描述的约定。

> 简单原则：**风格/格式细则查 .mdc；本仓库特有的目录、命令、流程查 AGENTS.md。** 若发现两边对同一件事说法不一致，以 `.cursor/rules` 为准并顺手把 AGENTS.md 修齐。

## 目录结构
- `main_gui.py`：应用入口（仓库根），负责启动主界面与页面装配。
- `pyproject.toml`：项目元数据与依赖（权威来源）。
- `src/`：可安装包源码根（通过 `pip install -e .` 注册到 venv）。
  - `src/core/`：核心业务逻辑，例如 CSV 导入、导出、更新、迁移等。
  - `src/db/`：数据库连接、SQL 执行及 PostgreSQL / ClickHouse 适配。
  - `src/gui/`：界面层代码。
    - `src/gui/app.py`：主壳 `MainApplication`（菜单/侧栏/页面装配）。
    - `src/gui/base/`：页面或组件的基础类。
    - `src/gui/components/`：可复用页面组件。
    - `src/gui/pages/`：具体业务页面逻辑。
    - `src/gui/styling/`：样式、主题和界面常量。
    - `src/gui/widgets/`：通用控件封装（含 `tooltip.py` 工具提示管理器）。
  - `src/utils/`：配置、日志、公共辅助工具。
- `tests/`：自动化测试；新增可测试逻辑时，优先补到这里。
- `docs/`：补充文档与说明材料。
- `build/`、`dist/`：打包产物目录，不作为日常手工修改目标。
- `__pycache__/`、`.pytest_cache/`：本地产物目录，不应作为有效改动提交。

> 业务代码导入仍按包名书写：`from core...`、`from db...`、`from gui...`、`from utils...`，不要写成 `from src.core...`。

## 开发原则
- 优先把业务逻辑放在 `core/`、`db/`、`utils/`，尽量减少页面事件处理函数里堆叠复杂逻辑。
- 页面级逻辑放在 `gui/pages/`，可复用 UI 能力放在 `gui/components/` 或 `gui/widgets/`；主壳装配放在 `gui/app.py`，`main_gui.py` 仅作为薄入口（创建根窗口、实例化 `MainApplication`、`mainloop`），不要把实现细节堆回去。
- 新增功能时先复用已有模块和模式，再考虑扩展目录结构，避免重复造轮子。
- 涉及配置、日志、连接信息时，统一走 `utils/` 或现有配置入口，不要在页面文件中硬编码路径、库名、账号规则等信息。

## 代码风格（仓库专属补充）
> 通用 Python 代码风格（PEP 8、命名规则、类型标注、文档字符串、import 顺序等）见 [`.cursor/rules/python.mdc`](.cursor/rules/python.mdc)，本节只列与本仓库相关的细节。

- 现有类名沿用历史 PascalCase，例如 `ImportCsvApp`、`ExportDbApp`、`MigratorPage`；新增类与之保持风格一致。
- Tkinter 界面代码以可读为先，较长页面逻辑主动拆分为辅助方法或挪到 `gui/components/` / `gui/widgets/`，不要在 `main_gui.py` 与单个 `pages/` 文件里堆。
- 注释以解释「为什么这样做」为主（业务上下文、规避的坑），避免重复代码字面含义。

## 常用命令
- **一次性**环境准备（仅首次创建 venv / 依赖或包发现规则有变更时重跑）：
  `python -m venv .venv` → `.\.venv\Scripts\Activate.ps1` → `pip install -e ".[dev]"`
- 日常启动与测试（仅需激活 venv，不要每次都跑可编辑安装）：
  - 启动应用：`python main_gui.py`
  - 快速语法检查：`python -m compileall src/core src/db src/gui src/utils main_gui.py`
  - 运行测试：`pytest`
- 打包单文件程序：
  `pyinstaller --clean --onefile --windowed --uac-admin --paths src --name "DB数据工具集" .\main_gui.py`

推荐顺序：
1. 先确认已 `pip install -e ".[dev]"`（仅首次或依赖变更时）
2. 执行 `python -m compileall src/core src/db src/gui src/utils main_gui.py`
3. 运行受影响的自动化测试，例如 `pytest` 或指定测试文件
4. 然后执行 `python main_gui.py` 做手工回归
5. 仅在需要发布安装包时再运行 `pyinstaller`

## 变更与验证要求
> 通用测试规范（fixture、参数化、mock、覆盖率等）见 [`.cursor/rules/pytest.mdc`](.cursor/rules/pytest.mdc)。

- 每次改动都要提供可重复的验证方式；如果无法补自动化测试，至少说明手工验证步骤。
- 优先为可独立验证的逻辑补测试，测试文件命名为 `tests/test_<module>.py`。
- 提交前至少完成以下检查：
  1. `python -m compileall src/core src/db src/gui src/utils main_gui.py`
  2. 运行受影响范围内的 `pytest` 用例；如果当前改动没有对应自动化测试，需说明原因
  3. 启动 `python main_gui.py`，验证受影响页面或流程
- 如果改动涉及导入导出、数据库更新或迁移流程，应尽量补充异常分支和空数据场景的验证。

## Git 与提交规范
- 一次提交只处理一个主题，避免把无关修改混在一起。
- `git commit` 提交信息采用“英文类型 + 中文描述”的格式，且保持简洁明确，推荐写成 `type: 描述`。
- 推荐示例：
  - `fix: 解决 CSV 导出编码异常`
  - `refactor: 调整连接配置校验提示`
  - `docs: 重写仓库协作说明`
- 提交前确认未误带 `build/`、`dist/`、`__pycache__/`、`.pytest_cache/` 等本地产物。
- 如需合并到主干，先确保当前分支验证通过，再执行合并，避免把未验证修改带入主分支。

## 打包与产物管理
- 打包前确认 `dist/` 中旧产物不会与本次输出混淆。
- 调试、验证完成后，不应保留无意义的缓存或打包产物作为待提交内容。
- 若更新打包方式、启动参数或发布产物名称，应同步检查 `README.md`、相关脚本和说明文档是否需要更新。

## 协作建议
- 修改前先查看受影响模块的上下游调用，避免只修页面表象而遗漏底层逻辑。
- 如果发现仓库现状与本文档不一致，应优先按仓库实际结构工作，并在本次改动中顺手更新文档说明。
- 对用户可见的文案、按钮、提示信息做调整时，尽量保持术语统一，避免同一概念出现多种说法。
