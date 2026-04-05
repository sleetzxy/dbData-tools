# Repository Guidelines

## 项目概览
这是一个基于 Tkinter 的 PostgreSQL 数据工具桌面应用，主要面向日常的数据导入、导出、更新与迁移场景。默认入口文件是 `main_gui.py`。改动时优先保持现有交互方式、页面组织和桌面端使用习惯的一致性。

## 目录结构
- `main_gui.py`：应用入口，负责启动主界面与页面装配。
- `core/`：核心业务逻辑，例如 CSV 导入、导出、更新、迁移等。
- `db/`：数据库连接、SQL 执行及 PostgreSQL 相关访问能力。
- `gui/`：界面层代码。
  - `gui/base/`：页面或组件的基础类。
  - `gui/components/`：可复用页面组件。
  - `gui/pages/`：具体业务页面逻辑。
  - `gui/styling/`：样式、主题和界面常量。
  - `gui/widgets/`：通用控件封装。
- `utils/`：配置、日志、公共辅助工具。
- `tests/`：自动化测试；新增可测试逻辑时，优先补到这里。
- `docs/`：补充文档与说明材料。
- `build/`、`dist/`：打包产物目录，不作为日常手工修改目标。
- `__pycache__/`、`.pytest_cache/`：本地产物目录，不应作为有效改动提交。

## 开发原则
- 优先把业务逻辑放在 `core/`、`db/`、`utils/`，尽量减少页面事件处理函数里堆叠复杂逻辑。
- 页面级逻辑放在 `gui/pages/`，可复用 UI 能力放在 `gui/components/` 或 `gui/widgets/`，不要持续把实现细节堆回 `main_gui.py`。
- 新增功能时先复用已有模块和模式，再考虑扩展目录结构，避免重复造轮子。
- 涉及配置、日志、连接信息时，统一走 `utils/` 或现有配置入口，不要在页面文件中硬编码路径、库名、账号规则等信息。

## 代码风格
- 使用 Python 标准 4 空格缩进。
- 文件名使用小写加下划线，例如 `exporter_csv.py`。
- 类名使用 PascalCase，例如 `ImportCsvApp`。
- 函数、变量、模块级辅助方法统一使用 snake_case。
- 注释以解释“为什么这样做”为主，避免重复代码字面含义。
- 保持 Tkinter 界面代码清晰可读；较长页面逻辑应主动拆分为辅助方法或可复用组件。

## 常用命令
- 启动应用：`python main_gui.py`
- 快速语法检查：`python -m compileall core db gui utils main_gui.py`
- 运行测试：`pytest`
- 打包单文件程序：
  `pyinstaller --clean --onefile --windowed --uac-admin --name "PostgreSQL数据工具集" .\main_gui.py`

推荐顺序：
1. 先执行 `python -m compileall core db gui utils main_gui.py`
2. 再运行受影响的自动化测试，例如 `pytest` 或指定测试文件
3. 然后执行 `python main_gui.py` 做手工回归
4. 仅在需要发布安装包时再运行 `pyinstaller`

## 变更与验证要求
- 每次改动都要提供可重复的验证方式；如果无法补自动化测试，至少说明手工验证步骤。
- 优先为可独立验证的逻辑补测试，测试文件命名建议为 `tests/test_<module>.py`。
- 提交前至少完成以下检查：
  1. `python -m compileall core db gui utils main_gui.py`
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
