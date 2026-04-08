# DB 数据工具集

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/GUI-Tkinter-informational" alt="Tkinter">
  <img src="https://img.shields.io/badge/DB-PostgreSQL-336791?logo=postgresql" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/DB-ClickHouse-yellow?logo=clickhouse" alt="ClickHouse">
  <img src="https://img.shields.io/badge/Platform-Windows-0078d4?logo=windows" alt="Windows">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
</p>

基于 Tkinter 的 Windows 桌面数据工具，支持 PostgreSQL 与 ClickHouse，涵盖 CSV 导入/导出、数据库导出、批量更新等常见数据操作，适合数据分析师与运维人员日常使用。

---

## 目录

- [功能特性](#功能特性)
- [截图预览](#截图预览)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [打包为可执行文件](#打包为可执行文件)
- [开发指南](#开发指南)
- [依赖清单](#依赖清单)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 功能特性

| 功能模块 | 描述 |
|----------|------|
| **CSV 导入** | 将 CSV / ZIP 压缩包（含 AES 加密）批量导入 PostgreSQL 或 ClickHouse 表 |
| **CSV 导入（类型推断）** | 自动推断列数据类型，按类型分配建表策略后再导入 |
| **CSV 导出** | 从数据库查询结果导出为 CSV 文件，支持自定义分隔符与编码 |
| **数据库导出** | 将整库或指定表导出为 SQL 脚本（`.sql`），方便备份与迁移 |
| **数据迁移** | 指定多张表从源库迁移到目标库，支持 PostgreSQL / ClickHouse 同构及异构迁移，可选迁移前清空目标表 |
| **CSV 更新** | 以 CSV 文件为数据源，对数据库中已有记录执行批量 UPDATE |
| **连接管理** | 图形化管理多个数据库连接配置，支持 PostgreSQL 与 ClickHouse |

**其他亮点：**
- 深色主题 UI，界面简洁清晰
- 操作日志实时滚动展示，方便排查问题
- 连接配置本地持久化（JSON），无需每次重填
- 支持加密 ZIP 解压（pyzipper AES-256）

---

## 截图预览

> *(可在此处插入应用截图)*

---

## 快速开始

### 环境要求

- Python 3.8+
- Windows 10/11（Tkinter 已内置于标准 Python 发行版）

### 安装依赖

```bash
pip install psycopg2-binary clickhouse-connect pyzipper
```

或使用 requirements.txt（如果已生成）：

```bash
pip install -r requirements.txt
```

### 启动应用

```bash
python main_gui.py
```

---

## 项目结构

```
dbData-tools/
├── main_gui.py              # 应用入口，初始化主窗口与标签页
├── core/                    # 业务逻辑层（与 GUI 解耦）
│   ├── importer_csv.py      # CSV / ZIP 导入核心逻辑
│   ├── importer_csv_type.py # 类型推断导入
│   ├── exporter_csv.py      # CSV 导出
│   ├── exporter_db.py       # 数据库 SQL 导出
│   └── updater_csv.py       # CSV 批量更新
├── db/                      # 数据库连接与适配器
│   ├── connection.py        # 统一连接入口
│   └── adapters/
│       ├── postgresql_adapter.py
│       └── clickhouse_adapter.py
├── gui/                     # 界面层
│   ├── pages/               # 各功能页面
│   │   ├── csv/             # CSV 相关页面
│   │   ├── database/        # 数据库导出页面
│   │   └── management/      # 连接管理页面
│   ├── base/                # 页面基类与 Mixin
│   ├── components/          # 可复用组件（连接选择器、路径选择器）
│   ├── widgets/             # 基础控件封装
│   ├── styling/             # 主题与样式
│   └── utils/               # GUI 工具函数
├── utils/                   # 通用工具
│   ├── config_manager.py    # JSON 配置读写
│   ├── logger_factory.py    # 日志工厂
│   └── log_handler.py       # 自定义日志处理器
├── tests/                   # 单元测试
├── docs/                    # 设计文档与规划
└── AGENTS.md                # 项目开发规范
```

---

## 配置说明

连接配置由 `utils/config_manager.py` 统一管理，以 JSON 格式保存在用户目录下（具体路径见各页面初始化逻辑）。首次运行时会自动创建空配置文件，在"连接管理"页面填写数据库信息后即可保存并复用。

**连接配置示例（PostgreSQL）：**

```json
{
  "host": "127.0.0.1",
  "port": 5432,
  "dbname": "my_database",
  "user": "postgres",
  "password": "your_password"
}
```

**连接配置示例（ClickHouse）：**

```json
{
  "host": "127.0.0.1",
  "port": 8123,
  "database": "default",
  "user": "default",
  "password": ""
}
```

> 注意：配置文件含有数据库密码，请勿将其提交到版本库。`.gitignore` 已包含常见配置文件路径的忽略规则。

---

## 打包为可执行文件

使用 PyInstaller 将应用打包为 Windows 单文件程序：

```bash
pyinstaller --clean --onefile --windowed --uac-admin --name "DB数据工具集" .\main_gui.py
```

打包完成后，可执行文件位于 `dist/` 目录。

> **说明：** PyInstaller 规格文件已加入 `clickhouse_connect` hidden import，避免打包后 ClickHouse 连接不可用。

---

## 开发指南

### 本地运行与验证

```bash
# 1. 语法检查
python -m compileall core db gui utils main_gui.py

# 2. 启动 GUI 手工验证
python main_gui.py

# 3. 运行单元测试
python -m pytest tests/
```

### 代码规范

- 缩进：4 空格
- 文件名：`snake_case`（如 `exporter_csv.py`）
- 类名：`PascalCase`（如 `ImportCsvApp`）
- 函数/变量：`snake_case`
- 业务逻辑放 `core/`，页面逻辑放 `gui/pages/`，勿堆入 `main_gui.py`

---

## 依赖清单

| 包名 | 用途 | 安装命令 |
|------|------|----------|
| `psycopg2-binary` | PostgreSQL 驱动 | `pip install psycopg2-binary` |
| `clickhouse-connect` | ClickHouse HTTP 客户端 | `pip install clickhouse-connect` |
| `pyzipper` | AES 加密 ZIP 解压 | `pip install pyzipper` |
| `tkinter` | GUI 框架（Python 标准库内置） | — |

完整依赖可通过以下命令生成：

```bash
pip freeze > requirements.txt
```

---

## 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库并 clone 到本地
2. 创建功能分支：`git checkout -b feat/your-feature`
3. 完成修改后执行 `python -m compileall ...` 与 GUI 手工验证
4. 提交信息使用简短祈使句，例如：`feat: 增加连接配置校验`
5. 推送分支并发起 Pull Request

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源，欢迎自由使用与修改。
