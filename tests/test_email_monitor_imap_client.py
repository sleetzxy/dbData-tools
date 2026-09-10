"""IMAP 客户端与 MonitorConfig 校验的单元测试（不连网）。"""

from __future__ import annotations

from datetime import date, timedelta
from email.message import EmailMessage
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from typing import Any

import pytest

from core.email_monitor.imap_client import (
    format_imap_since,
    iter_attachments_from_message,
    iter_matching_attachments,
)
from core.email_monitor.models import MonitorConfig, validate_monitor_config


def _valid_config(tmp_path: Any, **overrides: Any) -> MonitorConfig:
    """构造可通过校验的配置，允许覆盖字段。"""
    base = MonitorConfig(
        host="imap.example.com",
        port=993,
        use_ssl=True,
        account="user@example.com",
        password="secret",
        senders=["sender@example.com"],
        download_dir=str(tmp_path),
        extensions=[".csv", ".xlsx"],
        lookback_days=7,
        interval_seconds=60,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_monitor_config_defaults() -> None:
    cfg = MonitorConfig()
    assert cfg.host == "imap.exmail.qq.com"
    assert cfg.port == 993
    assert cfg.use_ssl is True
    assert cfg.lookback_days == 7
    assert cfg.interval_seconds == 60


def test_validate_rejects_empty_whitelist(tmp_path: Any) -> None:
    errors = validate_monitor_config(_valid_config(tmp_path, extensions=[]))
    assert any("白名单" in e or "扩展名" in e for e in errors)


def test_validate_rejects_missing_required_fields(tmp_path: Any) -> None:
    errors = validate_monitor_config(
        MonitorConfig(
            host="",
            port=993,
            account="",
            password="",
            senders=[],
            download_dir="",
            extensions=[],
            lookback_days=0,
            interval_seconds=0,
        )
    )
    assert any("主机" in e for e in errors)
    assert any("账号" in e for e in errors)
    assert any("密码" in e for e in errors)
    assert any("发件人" in e for e in errors)
    assert any("下载目录" in e for e in errors)
    assert any("白名单" in e or "扩展名" in e for e in errors)
    assert any("N 天" in e or "最近" in e for e in errors)
    assert any("间隔" in e for e in errors)


def test_validate_rejects_nonexistent_download_dir() -> None:
    errors = validate_monitor_config(
        MonitorConfig(
            account="a@x.com",
            password="p",
            senders=["b@y.com"],
            download_dir="/path/does/not/exist/email_monitor",
            extensions=[".csv"],
        )
    )
    assert any("下载目录" in e for e in errors)


def test_validate_passes_for_complete_config(tmp_path: Any) -> None:
    assert validate_monitor_config(_valid_config(tmp_path)) == []


def test_format_imap_since_uses_english_month() -> None:
    since = format_imap_since(7)
    expected = date.today() - timedelta(days=7)
    months = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    assert since == (
        f"{expected.day:02d}-{months[expected.month - 1]}-{expected.year}"
    )


def test_iter_attachments_skips_inline_image() -> None:
    """multipart: attachment csv + inline png → only csv。"""
    msg = MIMEMultipart()
    msg["From"] = "sender@example.com"
    msg["Subject"] = "mixed"

    csv_part = MIMEApplication(b"a,b\n1,2\n", Name="data.csv")
    csv_part.add_header("Content-Disposition", "attachment", filename="data.csv")
    msg.attach(csv_part)

    img_part = MIMEImage(b"\x89PNG\r\n\x1a\n", _subtype="png")
    img_part.add_header("Content-Disposition", "inline", filename="logo.png")
    msg.attach(img_part)

    attachments = list(iter_attachments_from_message(msg))
    assert len(attachments) == 1
    assert attachments[0][0] == "data.csv"
    assert attachments[0][1] == b"a,b\n1,2\n"


def test_iter_attachments_includes_filename_without_disposition() -> None:
    msg = EmailMessage()
    msg["From"] = "sender@example.com"
    msg.set_content("body")
    msg.add_attachment(
        b"hello",
        maintype="application",
        subtype="octet-stream",
        filename="report.xlsx",
    )

    names = [name for name, _ in iter_attachments_from_message(msg)]
    assert "report.xlsx" in names


def test_iter_attachments_chinese_zip_filename() -> None:
    """中文 zip 附件名应可提取且扩展名为 .zip。"""
    msg = MIMEMultipart()
    msg["From"] = "Xie <xiehaiying@pcitech.com>"
    filename = "长春交通大脑20260910版本csv.zip"
    zip_part = MIMEApplication(b"PK\x03\x04demo", Name=filename)
    zip_part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(zip_part)

    attachments = list(iter_attachments_from_message(msg))
    assert len(attachments) == 1
    assert attachments[0][0].endswith(".zip")
    from core.email_monitor.filters import extension_allowed

    assert extension_allowed(attachments[0][0], {".zip"})


def test_iter_matching_attachments_matches_reply_to(tmp_path: Any) -> None:
    """From 非白名单但 Reply-To 命中时仍应下载。"""
    msg = MIMEMultipart()
    msg["From"] = "relay@system.local"
    msg["Reply-To"] = "xiehaiying@pcitech.com"
    zip_part = MIMEApplication(b"PKDATA", Name="a.zip")
    zip_part.add_header("Content-Disposition", "attachment", filename="a.zip")
    msg.attach(zip_part)
    rfc822 = msg.as_bytes()

    fake = _FakeImap(rfc822)
    cfg = _valid_config(
        tmp_path,
        senders=["xiehaiying@pcitech.com"],
        extensions=[".zip"],
    )
    results = list(iter_matching_attachments(cfg, imap=fake))
    assert len(results) == 1
    assert results[0][1] == "a.zip"


class _FakeImap:
    """可注入的假 IMAP，断言必须走 UID 命令。"""

    def __init__(self, rfc822: bytes) -> None:
        self._rfc822 = rfc822
        self.uid_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.select_calls: list[str] = []

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        self.select_calls.append(mailbox)
        return "OK", [b"1"]

    def uid(self, command: str, *args: Any) -> tuple[str, Any]:
        self.uid_calls.append((command.upper(), args))
        cmd = command.upper()
        if cmd == "SEARCH":
            return "OK", [b"101"]
        if cmd == "FETCH":
            # imaplib 风格：[(b'101 (RFC822 {n}', bytes), b')']
            return "OK", [(b"101 (RFC822 {0}", self._rfc822), b")"]
        raise AssertionError(f"unexpected UID command: {command}")

    def search(self, *args: Any) -> None:
        raise AssertionError("禁止使用序号 SEARCH，必须 UID SEARCH")

    def fetch(self, *args: Any) -> None:
        raise AssertionError("禁止使用序号 FETCH，必须 UID FETCH")

    def logout(self) -> tuple[str, list[bytes]]:
        return "OK", [b"BYE"]


def _build_mail_bytes(*, from_addr: str, filename: str, payload: bytes) -> bytes:
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["Subject"] = "test"
    part = MIMEApplication(payload, Name=filename)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)
    return msg.as_bytes()


def test_iter_matching_attachments_uses_uid_search_and_fetch(tmp_path: Any) -> None:
    rfc822 = _build_mail_bytes(
        from_addr="sender@example.com",
        filename="data.csv",
        payload=b"col\n1\n",
    )
    fake = _FakeImap(rfc822)
    cfg = _valid_config(tmp_path)

    results = list(iter_matching_attachments(cfg, imap=fake))

    assert results == [("101", "data.csv", b"col\n1\n")]
    assert fake.select_calls == ["INBOX"]
    assert any(cmd == "SEARCH" for cmd, _ in fake.uid_calls)
    assert any(cmd == "FETCH" for cmd, _ in fake.uid_calls)
    search_args = next(args for cmd, args in fake.uid_calls if cmd == "SEARCH")
    assert any(
        isinstance(a, str) and a.upper().startswith("SINCE ") for a in search_args
    )


def test_iter_matching_attachments_filters_sender_and_extension(
    tmp_path: Any,
) -> None:
    rfc822 = _build_mail_bytes(
        from_addr="other@example.com",
        filename="data.csv",
        payload=b"x",
    )
    fake = _FakeImap(rfc822)
    cfg = _valid_config(tmp_path, senders=["sender@example.com"])

    assert list(iter_matching_attachments(cfg, imap=fake)) == []
