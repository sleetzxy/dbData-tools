# ClickHouse 支持设计说明

**日期：** 2026-03-25  
**主题：** 为 PostgreSQL 数据工具增加 ClickHouse 连接、CSV 导入导出、SQL 导出支持

## 目标
在保持现有 GUI 与 PostgreSQL 功能可用的前提下，引入 ClickHouse 支持。连接配置需要能够区分数据库类型；CSV 导入、CSV 导出、SQL 导出需要根据连接类型自动分流到 PostgreSQL 或 ClickHouse 实现。

## 当前现状
- 连接配置由 `gui/pages/management/connection.py` 管理，保存到 `~/.connections.json`
- 数据库连接在 `db/connection.py` 中，当前只支持 `psycopg2`
- `core/importer_csv.py`、`core/exporter_csv.py`、`core/exporter_db.py` 当前都直接依赖 PostgreSQL 行为
- GUI 通过选择连接来驱动导入导出流程，因此最合适的改造点是连接配置与后端适配层

## 设计结论
采用“**适配器分层**”方案，而不是在现有文件中继续堆积 `if/else`：
- 连接配置新增 `db_type`
- 引入 PostgreSQL / ClickHouse 双适配器
- `core` 层只做流程编排
- GUI 只在连接管理界面增加数据库类型选择，并在列表中展示数据库类型

## 连接配置设计
连接项扩展为：
- `name`
- `db_type`：`postgresql` 或 `clickhouse`
- `host`
- `port`
- `database`
- `schema`
- `user`
- `password`

兼容策略：
- 历史连接没有 `db_type` 时，默认按 `postgresql` 处理
- PostgreSQL 默认端口为 `5432`，默认 `schema` 为 `public`
- ClickHouse 默认端口为 `8123`，`schema` 对其为可忽略字段

## GUI 改造
文件：`gui/pages/management/connection.py`

改动要求：
1. 在新增/编辑连接表单中加入数据库类型下拉框：`PostgreSQL`、`ClickHouse`
2. 切换类型时联动默认值：
   - PostgreSQL -> `5432` / `public`
   - ClickHouse -> `8123` / 空 schema
3. 在连接列表中新增“类型”列，避免多库连接无法区分
4. 读取老连接时自动补齐 `db_type=postgresql`

## 后端分层设计
建议新增：
- `db/adapters/postgresql_adapter.py`
- `db/adapters/clickhouse_adapter.py`
- `db/adapters/__init__.py`

职责划分：
- `db/connection.py`：按 `db_type` 创建连接 / 客户端
- 各适配器：封装各自数据库的元数据查询、CSV 导入导出、SQL 导出
- `core` 层：根据连接配置获取适配器，组织流程、日志和结果汇总

## PostgreSQL 行为
保留现有能力：
- 连接：`psycopg2`
- CSV 导出：`COPY ... TO STDOUT`
- CSV 导入：`COPY ... FROM STDOUT`
- SQL 导出：按现有逻辑输出表结构与数据插入语句
- 事务：保留现有事务控制与回滚行为

## ClickHouse 行为
驱动：`clickhouse-connect`

实现要求：
- 连接：通过 `clickhouse_connect.get_client(...)` 建立客户端
- CSV 导出：使用 `SELECT * FROM database.table FORMAT CSVWithNames`
- CSV 导入：使用 `INSERT INTO database.table FORMAT CSVWithNames`
- 表清空：使用 `TRUNCATE TABLE database.table`
- SQL 导出：
  - 表结构：`SHOW CREATE TABLE database.table`
  - 数据：生成 `INSERT INTO ... VALUES (...)` 语句并写入单个 `.sql` 文件

注意点：
- ClickHouse 不应被强行套入 PostgreSQL 的 `schema` 模型
- ClickHouse 不按 PostgreSQL 事务模型处理，结果汇总应按“逐表成功/失败”记录
- 错误日志应显式带数据库类型，便于排查

## core 层改造范围
需要调整：
- `core/importer_csv.py`
- `core/exporter_csv.py`
- `core/exporter_db.py`

改造目标：
- 去掉对 `psycopg2` 和 PostgreSQL 专属 SQL 的直接依赖
- 统一通过 `db_type` 获取适配器
- 继续保留当前返回结构，避免 GUI 跟着大改

## 兼容性要求
- 不破坏现有 PostgreSQL 用户配置
- 不要求用户手动迁移旧连接文件
- 其他 GUI 页面尽量不改动交互结构，只改后端分流逻辑

## 验证范围
至少覆盖：
1. 新增 / 编辑 PostgreSQL 与 ClickHouse 连接
2. 历史 PostgreSQL 连接兼容读取
3. PostgreSQL CSV 导入导出正常
4. ClickHouse CSV 导入导出正常
5. PostgreSQL SQL 导出正常
6. ClickHouse SQL 导出正常
7. 连接失败、表不存在、字段不匹配时错误信息清晰

## 非目标
本次不包含：
- 第三种数据库支持
- 大规模 GUI 重构
- 统一 PostgreSQL 与 ClickHouse 的 SQL 语义模型
- 与当前需求无关的重构
