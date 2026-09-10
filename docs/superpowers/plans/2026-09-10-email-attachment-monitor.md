# 邮件附件定时监控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在应用内提供 IMAP 邮件附件监控页：按间隔拉取指定发件人最近 N 天邮件的附件，按扩展名白名单过滤后下载到指定目录，并支持本机去重与启停。

**Architecture:** 业务在 `core/email_monitor/`（过滤、落盘、去重、IMAP、后台 Service）；GUI 继承 `BaseToolPage` 左右分栏托管 Service 生命周期；密码经 `utils/credential_crypto.py` 落盘混淆存储；侧栏「数据进出」注册新页，关应用时停止监控。

**Tech Stack:** Python 3.10+、标准库 `imaplib`/`email`/`threading`、CustomTkinter、`ConfigManager`、`pytest` + mock；不新增第三方邮件库。

**Spec:** `docs/superpowers/specs/2026-09-10-email-attachment-monitor-design.md`

**提交约定：** 本仓库可用普通 `git commit -m "..."`（中文 Conventional Commits 风格即可）；**不要**使用 `git-commit-structured` skill。

---

## File Structure

| 路径 | 职责 |
|------|------|
| `src/utils/credential_crypto.py` | 密码落盘混淆/还原（非明文） |
| `src/core/email_monitor/__init__.py` | 包导出 |
| `src/core/email_monitor/models.py` | `MonitorConfig` 数据类与默认值 |
| `src/core/email_monitor/filters.py` | 发件人匹配、扩展名白名单 |
| `src/core/email_monitor/saver.py` | 附件落盘与同名重命名 |
| `src/core/email_monitor/dedup.py` | 去重键持久化 |
| `src/core/email_monitor/imap_client.py` | IMAP 连接/检索/解析附件 |
| `src/core/email_monitor/service.py` | 后台轮询、失败计数、协作停止 |
| `src/gui/pages/email/__init__.py` | 页面包导出 |
| `src/gui/pages/email/monitor.py` | `EmailMonitorPage` |
| `src/gui/app.py` | 侧栏注册、加载页、关闭时停监控 |
| `tests/test_credential_crypto.py` | 加密工具测试 |
| `tests/test_email_monitor_filters.py` | 过滤测试 |
| `tests/test_email_monitor_saver.py` | 落盘重命名测试 |
| `tests/test_email_monitor_dedup.py` | 去重测试 |
| `tests/test_email_monitor_imap_client.py` | IMAP 解析与校验测试 |
| `tests/test_email_monitor_service.py` | Service + mock IMAP |
| `AGENTS.md` / `CLAUDE.md` | 目录说明补充（末尾任务） |

---

### Task 1: 密码落盘混淆工具

**Files:**
- Create: `src/utils/credential_crypto.py`
- Test: `tests/test_credential_crypto.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_credential_crypto.py
from utils.credential_crypto import decrypt_secret, encrypt_secret


def test_roundtrip_preserves_plaintext(tmp_path, monkeypatch):
    key_file = tmp_path / ".secret_key"
    monkeypatch.setenv("DBDATA_SECRET_KEY_FILE", str(key_file))
    token = encrypt_secret("my-auth-code")
    assert token != "my-auth-code"
    assert not token.startswith("my-auth")
    assert decrypt_secret(token) == "my-auth-code"


def test_empty_string_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DBDATA_SECRET_KEY_FILE", str(tmp_path / "k"))
    assert decrypt_secret(encrypt_secret("")) == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_credential_crypto.py -v`  
Expected: FAIL（模块不存在）

- [ ] **Step 3: 最小实现**

实现要点：
- 密钥文件默认 `~/.dbdata_tools/.secret_key`（可用环境变量 `DBDATA_SECRET_KEY_FILE` 覆盖，便于测试）
- 首次自动生成随机 32 字节密钥并写入文件（权限尽量受限）
- 使用 `hashlib` + XOR 流或等价标准库方案，前缀标记如 `enc:v1:`，禁止明文写入配置
- 类型标注 + 简体中文 docstring

- [ ] **Step 4: 测试通过**

Run: `pytest tests/test_credential_crypto.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/utils/credential_crypto.py tests/test_credential_crypto.py
git commit -m "feat(email-monitor): add local credential obfuscation helper"
```

---

### Task 2: 发件人与扩展名过滤

**Files:**
- Create: `src/core/email_monitor/__init__.py`
- Create: `src/core/email_monitor/filters.py`
- Test: `tests/test_email_monitor_filters.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_email_monitor_filters.py
from core.email_monitor.filters import (
    extension_allowed,
    normalize_extensions,
    parse_sender_list,
    sender_matches,
)


def test_parse_sender_list_comma_and_newline():
    assert parse_sender_list("a@x.com, b@y.com\nc@z.com") == {
        "a@x.com",
        "b@y.com",
        "c@z.com",
    }


def test_sender_matches_ignores_display_name_and_case():
    allowed = {"foo@bar.com"}
    assert sender_matches("Foo Bar <FOO@BAR.COM>", allowed)
    assert not sender_matches("other@bar.com", allowed)


def test_extension_whitelist_required_semantics():
    assert normalize_extensions(".CSV, xlsx") == {".csv", ".xlsx"}
    assert extension_allowed("report.CSV", {".csv"})
    assert not extension_allowed("report.txt", {".csv"})
    assert not extension_allowed("report.csv", set())  # 空白名单不下任何文件
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_email_monitor_filters.py -v`  
Expected: FAIL

- [ ] **Step 3: 实现 `filters.py`**

- `parse_sender_list`：按逗号/换行拆分，strip，小写
- `sender_matches`：用 `email.utils.parseaddr` 取地址，大小写不敏感精确匹配
- `normalize_extensions`：补前导点、小写；空输入 → 空 set
- `extension_allowed`：空白名单恒为 False

- [ ] **Step 4: 测试通过**

Run: `pytest tests/test_email_monitor_filters.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/email_monitor/__init__.py src/core/email_monitor/filters.py tests/test_email_monitor_filters.py
git commit -m "feat(email-monitor): add sender and extension filters"
```

---

### Task 3: 附件落盘与同名重命名

**Files:**
- Create: `src/core/email_monitor/saver.py`
- Test: `tests/test_email_monitor_saver.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_email_monitor_saver.py
from pathlib import Path

from core.email_monitor.saver import save_attachment_bytes


def test_save_creates_file(tmp_path: Path):
    path = save_attachment_bytes(tmp_path, "a.csv", b"hello")
    assert path == tmp_path / "a.csv"
    assert path.read_bytes() == b"hello"


def test_save_renames_on_collision(tmp_path: Path):
    (tmp_path / "a.csv").write_bytes(b"old")
    path = save_attachment_bytes(tmp_path, "a.csv", b"new")
    assert path == tmp_path / "a_1.csv"
    assert path.read_bytes() == b"new"
    assert (tmp_path / "a.csv").read_bytes() == b"old"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_email_monitor_saver.py -v`  
Expected: FAIL

- [ ] **Step 3: 实现 `unique_path` + `save_attachment_bytes`**

规则：`name.ext` → `name_1.ext` → `name_2.ext`…；拒绝路径穿越（仅取 `Path(filename).name`）。

- [ ] **Step 4: 测试通过**

Run: `pytest tests/test_email_monitor_saver.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/email_monitor/saver.py tests/test_email_monitor_saver.py
git commit -m "feat(email-monitor): save attachments with collision rename"
```

---

### Task 4: 去重存储

**Files:**
- Create: `src/core/email_monitor/dedup.py`
- Test: `tests/test_email_monitor_dedup.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_email_monitor_dedup.py
from core.email_monitor.dedup import DedupStore, make_dedup_key


def test_make_dedup_key_includes_account():
    assert make_dedup_key("u@x.com", "123", "a.csv") == "u@x.com|123|a.csv"


def test_dedup_store_persists(tmp_path):
    store = DedupStore(tmp_path / "seen.json")
    key = make_dedup_key("u@x.com", "1", "a.csv")
    assert not store.has(key)
    store.add(key)
    assert store.has(key)
    store2 = DedupStore(tmp_path / "seen.json")
    assert store2.has(key)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_email_monitor_dedup.py -v`  
Expected: FAIL

- [ ] **Step 3: 实现 `DedupStore`**

JSON 列表或 set 落盘；`add` 后立即保存；文件损坏时当作空集并打日志（可用标准 logging）。

- [ ] **Step 4: 测试通过**

Run: `pytest tests/test_email_monitor_dedup.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/email_monitor/dedup.py tests/test_email_monitor_dedup.py
git commit -m "feat(email-monitor): persist attachment dedup keys"
```

---

### Task 5: MonitorConfig 与 IMAP 客户端（可 mock）

**Files:**
- Create: `src/core/email_monitor/models.py`
- Create: `src/core/email_monitor/imap_client.py`
- Test: `tests/test_email_monitor_imap_client.py`

- [ ] **Step 1: 定义 `MonitorConfig` dataclass**

字段：`host`, `port`, `use_ssl`, `account`, `password`, `senders: list[str]`, `download_dir`, `extensions: list[str]`, `lookback_days: int`, `interval_seconds: int`  
默认：`imap.exmail.qq.com`, `993`, `True`, `lookback_days=7`, `interval_seconds=60`

校验函数 `validate_monitor_config(cfg) -> list[str]`：返回错误文案列表（空=通过）。须覆盖规格 §4.1 必填项；白名单空 → 错误。

- [ ] **Step 2: 写 IMAP 解析/过滤单元测试（不连网）**

对「从 MIME bytes 提取附件」与「SINCE 日期格式」做纯函数测试；`fetch_matching_attachments` 接受可注入的 imap 对象或拆出 `iter_attachments_from_message(msg)`。

示例：

```python
def test_iter_attachments_skips_inline_image():
    # 构造 multipart：一个 Content-Disposition: attachment 的 csv
    # 一个 inline 的 png；只应得到 csv
    ...


def test_validate_rejects_empty_whitelist():
    errors = validate_monitor_config(...)
    assert any("白名单" in e or "扩展名" in e for e in errors)
```

- [ ] **Step 3: 实现 `imap_client.py`**

- `test_connection(cfg)`：SSL/非 SSL 连接 → login → `SELECT INBOX` → logout
- **必须使用 UID 命令**（规格去重键依赖稳定 mailbox UID，禁止用序号）：
  - 检索：`UID SEARCH SINCE <dd-Mon-yyyy>`（勿用普通 `SEARCH`）
  - 取信：`UID FETCH <uid> (RFC822)`（或等价 BODY.PEEK[]；勿用序号 `FETCH`）
  - yield 的 `uid` 必须是 IMAP UID 字符串/整数，写入去重键
- `iter_new_attachments(cfg, ...)`：解析 From、附件判定（`Content-Disposition: attachment` 或带 filename 的 part）、yield `(uid, filename, payload_bytes)`
- 固定文件夹 `INBOX`

- [ ] **Step 4: 测试通过**

Run: `pytest tests/test_email_monitor_imap_client.py tests/test_email_monitor_filters.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/email_monitor/models.py src/core/email_monitor/imap_client.py tests/test_email_monitor_imap_client.py
git commit -m "feat(email-monitor): add monitor config and IMAP attachment fetch"
```

---

### Task 6: EmailMonitorService 轮询服务

**Files:**
- Create: `src/core/email_monitor/service.py`
- Modify: `src/core/email_monitor/__init__.py`（导出 Service / Config）
- Test: `tests/test_email_monitor_service.py`

- [ ] **Step 1: 写失败测试（mock tick 依赖）**

行为要求（规格）：
- `start(config_snapshot)`：立即执行首轮 tick，再按 `interval_seconds` 循环
- `stop()`：协作停止，线程结束
- 单轮异常：记日志，连续失败 +1；成功清零
- 连续失败 ≥ 5：调用可选 `on_fatal(message)` 回调并 stop
- tick 内：过滤 → 去重 → 保存 → add dedup；单附件失败不中断其余

```python
def test_service_stops_after_five_consecutive_failures(mocker):
    ...


def test_service_skips_deduped_attachment(tmp_path, mocker):
    ...
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_email_monitor_service.py -v`  
Expected: FAIL

- [ ] **Step 3: 实现 Service**

- 守护线程或普通后台线程均可；`stop` 设置 Event，间隔休眠用 `wait(timeout=)` 以便快速退出
- 日志用注入的 `logging.Logger`
- 去重文件默认：`~/.dbdata_tools/email_monitor_seen.json`

- [ ] **Step 4: 测试通过**

Run: `pytest tests/test_email_monitor_service.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/email_monitor/service.py src/core/email_monitor/__init__.py tests/test_email_monitor_service.py
git commit -m "feat(email-monitor): add background polling monitor service"
```

---

### Task 7: EmailMonitorPage GUI

**Files:**
- Create: `src/gui/pages/email/__init__.py`
- Create: `src/gui/pages/email/monitor.py`

- [ ] **Step 1: 实现页面骨架**

- `CONFIG_FILE = "~/.dbdata_tools/email_monitor.json"`
- `TASK_TYPE = "email_monitor"`
- `REQUIRES_ACTIVE_CONNECTION = False`
- 继承 `BaseToolPage`；`log_title="📋 邮件监控日志"`
- **不要**展示数据库「当前连接」页头
- 左侧字段按规格表格；密码框 `show="●"`
- 按钮：测试连接、保存配置、开始监控、停止（启停互斥）
- `execute_task`：可返回 `{"success": True}` 空实现，或抛出 `NotImplementedError` 但基类若可能调用则改为安全空实现——实际启停走自定义方法，避免误触基类一次性任务流

- [ ] **Step 2: 配置读写**

- `get_config_dict`：密码经 `encrypt_secret` 后写入；其余明文
- `apply_config`：密码 `decrypt_secret` 填入框；缺省用腾讯企业邮默认主机/端口
- 「保存配置」调用 `save_current_config`

- [ ] **Step 3: 测试连接 / 开始 / 停止**

- 测试连接：后台线程调 `test_connection`，UI 线程弹窗 + 日志
- 开始：调用 `validate_monitor_config`（与 core 共用 §4.1 全量校验，含目录存在/可写）→ 快照 `MonitorConfig` → `_begin_task_history` → `service.start`；`on_fatal` 用 `root.after` 弹窗并 `_finish_task_history(failed)`
- 停止：`service.stop` → 用 `update_task(..., status="success", summary="用户停止监控")`（或项目已有 cancelled 语义）更新任务历史，勿依赖仅写「任务执行成功」的默认摘要
- 提供 `stop_monitor_if_running()` 供主壳关闭时调用

- [ ] **Step 4: 语法检查**

Run: `python -m compileall src/gui/pages/email src/core/email_monitor src/utils/credential_crypto.py`  
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add src/gui/pages/email/__init__.py src/gui/pages/email/monitor.py
git commit -m "feat(email-monitor): add email attachment monitor page"
```

---

### Task 8: 主壳导航与关闭清理

**Files:**
- Modify: `src/gui/app.py`
- Modify: `AGENTS.md`（目录结构补一句）
- Modify: `CLAUDE.md`（同上，保持与 AGENTS 一致）

- [ ] **Step 1: 注册侧栏**

在 `_build_nav_groups` 的「数据进出」列表末尾增加：

```python
("email_monitor", "邮件附件监控", self.load_email_monitor),
```

增加 `load_email_monitor`、shortcut/`_navigate_to_page` loaders 映射条目（若任务历史「重跑」走该 map，需能打开本页）；import `EmailMonitorPage`。

- [ ] **Step 2: `_on_closing` 停监控**

```python
def _on_closing(self):
    page = self.pages.get("email_monitor") if hasattr(self, "pages") else None
    if page is not None and hasattr(page, "stop_monitor_if_running"):
        page.stop_monitor_if_running()
    self.tooltip_manager.cleanup()
    self.root.quit()
```

- [ ] **Step 3: 更新文档目录说明**

`AGENTS.md` / `CLAUDE.md` 的 `gui/pages/` 说明中补充 email 监控页（一句话即可）。

- [ ] **Step 4: 回归命令**

Run:

```bash
python -m compileall src/core src/db src/gui src/utils main_gui.py
pytest tests/test_credential_crypto.py tests/test_email_monitor_filters.py tests/test_email_monitor_saver.py tests/test_email_monitor_dedup.py tests/test_email_monitor_imap_client.py tests/test_email_monitor_service.py -q
```

Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/gui/app.py AGENTS.md CLAUDE.md
git commit -m "feat(email-monitor): wire monitor page into sidebar and shutdown"
```

---

### Task 9: 手工验收清单（不写代码）

- [ ] **Step 1: 启动应用** `python main_gui.py`
- [ ] **Step 2: 打开「数据进出 → 邮件附件监控」**
- [ ] **Step 3: 填腾讯企业邮账号/授权码，点「测试连接」**
- [ ] **Step 4: 配置发件人、目录、白名单，开始监控；确认日志与落盘**
- [ ] **Step 5: 停止监控；关应用确认无残留线程（进程退出）**

（真实邮箱验收由人工完成；自动化不连外网。）

---

## 执行备注

- 严格 TDD：先测后码；每 Task 结束提交一次
- 密码存储：本机密钥文件混淆即可满足规格「不明文」；勿把密钥提交进仓库
- `BaseToolPage.REQUIRES_ACTIVE_CONNECTION = False` 后主按钮不被数据库连接禁用
- 若 `execute_task` 抽象方法强制实现：返回 `{"success": True, "error": "请使用开始监控按钮"}` 并避免基类「运行」按钮出现在本页
