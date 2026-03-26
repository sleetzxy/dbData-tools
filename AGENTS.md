# Repository Guidelines

## 项目结构与模块组织
这是一个基于 Tkinter 的 PostgreSQL 数据工具桌面应用。入口在 `main_gui.py`。`core/` 放 CSV 导入、导出、更新等业务逻辑；`db/` 管数据库连接；`gui/` 下再分 `base/`、`components/`、`pages/`、`styling/`、`widgets/`，用于组织界面层；`utils/` 负责配置与日志。`build/`、`dist/` 是打包输出目录，通常不作为手工修改目标。

## 本地开发与常用命令
- `python main_gui.py`：直接启动 GUI，适合做日常回归。
- `python -m compileall core db gui utils main_gui.py`：快速检查语法是否有效。
- `pyinstaller --clean --onefile --windowed --uac-admin --name "PostgreSQL数据工具集" .\main_gui.py`：打包生成 Windows 单文件程序，与当前 README 保持一致。

建议顺序：先跑 `compileall`，再启动 GUI 手工验证，最后再打包。

## 代码风格与命名约定
统一使用 Python 4 空格缩进。文件名用小写加下划线，例如 `exporter_csv.py`；类名用 PascalCase，例如 `ImportCsvApp`；函数和变量使用 snake_case。页面逻辑应优先放在 `gui/pages/`，通用控件放在 `gui/components/` 或 `gui/widgets/`，避免把实现细节继续堆回 `main_gui.py`。

## 自测与回归要求
当前仓库没有独立 `tests/` 目录，因此每次改动都应附带可重复的手工验证步骤。优先把可测试逻辑写在 `core/`、`db/`，减少与 GUI 事件强耦合。提交前至少完成两项：1）执行 `python -m compileall ...`；2）运行 `python main_gui.py` 验证受影响页面。若后续补测试文件，建议命名为 `tests/test_<module>.py`。

## 个人提交建议
当前目录缺少 `.git` 历史，这里给出推荐做法：一次提交只处理一个主题，提交信息写成简短祈使句，例如 `feat: 增加连接配置校验`、`fix: 修复 CSV 导出编码问题`。如果这次修改只是在验证想法，不要顺手提交 `build/`、`dist/`、`__pycache__/` 等本地产物。

## 配置与产物管理
配置、日志、连接信息应尽量统一走 `utils/` 模块，不要把路径、库名、账号规则直接硬编码到页面文件。打包前确认 `dist/` 中旧产物不会混淆本次结果；调试完成后，`__pycache__/`、`build/` 这类目录不应作为有效改动保留。
