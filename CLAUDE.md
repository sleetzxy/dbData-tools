# CLAUDE.md

## 项目概览

基于 Tkinter (CustomTkinter) 的 PostgreSQL 数据工具桌面应用，面向数据导入、导出、更新与迁移场景。默认入口 `main_gui.py`。

- Python 3.10+，`src/` 布局，setuptools 构建
- GUI: Tkinter + CustomTkinter 5.2.2
- 数据库: PostgreSQL (psycopg2) + ClickHouse (clickhouse-connect)
- Lint/Format: ruff（line-length=88, double-quote），pyright（basic 模式）
- 测试: pytest + pytest-mock

## 规范层次

1. **`.claude/rules/*.md`（团队通用规范，权威）** — 由 Claude Code 按文件路径自动注入，冲突以此为准：
   - `.claude/rules/python.md`：Python 编码规范（PEP 8、类型标注、命名、常见模式）
   - `.claude/rules/pytest.md`：pytest 测试规范（布局、fixture、mock、参数化）
   - `.claude/rules/git-commit-conventions.md`：Git 提交规范（Angular 约定式提交、AI 辅助标注）
2. **`CLAUDE.md`（本文件，仓库专属补充）** — 目录结构、开发原则、命令与流程等无法在通用 rule 里描述的约定。

> 原则：风格/格式细则查 `.claude/rules/`；仓库特有的目录、命令、流程查 `CLAUDE.md`。冲突以 `.claude/rules/` 为准。

## 目录结构

```
main_gui.py              # 应用入口（薄入口：创建根窗口 → MainApplication → mainloop）
src/
  core/                   # 核心业务逻辑（CSV 导入导出、更新、迁移等）
  db/                     # 数据库连接、SQL 执行、PG/ClickHouse 适配
  gui/
    app.py                # 主壳 MainApplication（菜单/侧栏/页面装配）
    base/                 # 页面/组件基础类
    components/           # 可复用页面组件
    pages/                # 具体业务页面逻辑
    styling/              # 样式、主题、界面常量
    widgets/              # 通用控件封装（含 tooltip.py）
  utils/                  # 配置、日志、公共辅助工具
tests/                    # 自动化测试
```

> **注意**：`src/gui/` 下不要保留与 `app.py` 同名的空目录 `app/`，否则 `import gui.app` 可能解析为包而非模块。
>
> 业务代码导入按包名书写：`from core...`、`from db...`、`from gui...`、`from utils...`，不要写成 `from src.core...`。

## 开发原则

- 业务逻辑放 `core/`、`db/`、`utils/`，不在页面事件处理函数里堆复杂逻辑。
- 页面逻辑放 `gui/pages/`，可复用 UI 放 `gui/components/` 或 `gui/widgets/`。
- 主壳装配放 `gui/app.py`，`main_gui.py` 仅作薄入口（创建根窗口、实例化 `MainApplication`、`mainloop`），不堆实现细节。
- 新增功能先复用已有模块和模式，再考虑扩展目录结构，避免重复造轮子。
- 配置、日志、连接信息统一走 `utils/` 或现有配置入口，不在页面文件硬编码路径、库名、账号规则等。
- Tkinter 界面代码以可读为先，较长页面逻辑主动拆分为辅助方法或挪到 `gui/components/` / `gui/widgets/`。
- 注释解释「为什么这样做」，不重复代码字面含义。

## 常用命令

### 环境准备（仅首次或依赖变更时）

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 日常开发（先激活 venv）

```bash
python -m compileall src/core src/db src/gui src/utils main_gui.py   # 语法检查
pytest                                                                # 运行测试
python main_gui.py                                                    # 启动应用
```

### 打包

```bash
pyinstaller --clean --onefile --windowed --uac-admin --paths src --name "DB数据工具集" .\main_gui.py
```

### 验证流程

1. `python -m compileall src/core src/db src/gui src/utils main_gui.py`
2. `pytest`（或指定受影响测试文件）
3. `python main_gui.py` 手工回归受影响页面或流程
4. 仅在需发布时运行 pyinstaller

## 打包与产物管理

- 打包前确认 `dist/` 中旧产物不会与本次输出混淆。
- 不应保留无意义的缓存或打包产物作为待提交内容：`build/`、`dist/`、`__pycache__/`、`.pytest_cache/`、`*.egg-info/`。
- 若更新打包方式、启动参数或发布产物名称，同步检查 `README.md` 和相关说明文档。

## 协作建议

- 修改前先查看受影响模块的上下游调用，避免只修页面表象而遗漏底层逻辑。
- 发现仓库现状与本文档不一致时，按仓库实际结构工作，并在本次改动中顺手更新文档。
- 对用户可见的文案、按钮、提示信息做调整时保持术语统一。
