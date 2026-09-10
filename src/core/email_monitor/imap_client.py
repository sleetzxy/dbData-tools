"""IMAP 连接、检索与附件解析（标准库，可注入 mock）。"""

from __future__ import annotations

import email
import imaplib
from datetime import date, timedelta
from email.message import Message
from typing import Any, Iterator, Optional

from core.email_monitor.filters import (
    extension_allowed,
    normalize_extensions,
    sender_matches,
)
from core.email_monitor.models import MonitorConfig

# IMAP SINCE 要求英文月份缩写，避免依赖系统 locale
_IMAP_MONTHS = (
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


def format_imap_since(lookback_days: int) -> str:
    """将 lookback_days 转为 IMAP ``SINCE`` 日期字符串（``dd-Mon-yyyy``）。

    :param lookback_days: 回溯天数。
    :return: 英文月份的 SINCE 日期。
    """
    target = date.today() - timedelta(days=lookback_days)
    return f"{target.day:02d}-{_IMAP_MONTHS[target.month - 1]}-{target.year}"


def iter_attachments_from_message(msg: Message) -> Iterator[tuple[str, bytes]]:
    """从 MIME 消息中提取附件（文件名, 内容）。

    规则：``Content-Disposition: attachment`` 或带 filename 的 part；
    跳过纯内联图片。

    :param msg: 已解析的邮件消息。
    :return: ``(filename, payload_bytes)`` 迭代器。
    """
    for part in msg.walk():
        if part.is_multipart():
            continue

        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        maintype = part.get_content_maintype()

        # 跳过纯内联图 / 签名图
        if disposition == "inline" and maintype == "image":
            continue

        if disposition != "attachment" and not filename:
            continue

        if not filename:
            # attachment 但无文件名时给一个可识别的占位名
            subtype = part.get_content_subtype() or "bin"
            filename = f"attachment.{subtype}"

        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        if not isinstance(payload, (bytes, bytearray)):
            continue

        yield filename, bytes(payload)


def test_connection(cfg: MonitorConfig) -> None:
    """测试 IMAP 连接：连接 → 登录 → SELECT INBOX → 登出。

    :param cfg: 监控配置。
    :raises OSError: 网络或协议错误。
    :raises imaplib.IMAP4.error: 登录或 SELECT 失败。
    """
    client = _open_client(cfg)
    try:
        client.login(cfg.account, cfg.password)
        status, _ = client.select("INBOX")
        if status != "OK":
            raise imaplib.IMAP4.error("SELECT INBOX 失败")
    finally:
        try:
            client.logout()
        except Exception:
            # 登出失败不影响连接测试主结果
            pass


def iter_matching_attachments(
    cfg: MonitorConfig,
    imap: Optional[Any] = None,
) -> Iterator[tuple[str, str, bytes]]:
    """检索匹配发件人与扩展名白名单的附件。

    必须使用 ``UID SEARCH`` / ``UID FETCH``，yield 的 uid 为 IMAP UID。

    :param cfg: 监控配置。
    :param imap: 可选已连接的 IMAP 对象（便于单测注入）；为 ``None`` 时自行连接。
    :return: ``(uid, filename, payload_bytes)`` 迭代器。
    """
    owns_connection = imap is None
    client = imap if imap is not None else _open_client(cfg)

    try:
        if owns_connection:
            client.login(cfg.account, cfg.password)

        status, _ = client.select("INBOX")
        if status != "OK":
            raise imaplib.IMAP4.error("SELECT INBOX 失败")

        since = format_imap_since(cfg.lookback_days)
        typ, data = client.uid("SEARCH", None, f"SINCE {since}")
        if typ != "OK" or not data or data[0] is None:
            return

        uid_bytes = data[0]
        if isinstance(uid_bytes, int):
            return
        raw_uids = uid_bytes.split()
        if not raw_uids:
            return

        allowed_senders = {s.strip().lower() for s in cfg.senders if s.strip()}
        allowed_exts = normalize_extensions(",".join(cfg.extensions))

        for raw_uid in raw_uids:
            uid = (
                raw_uid.decode("ascii")
                if isinstance(raw_uid, (bytes, bytearray))
                else str(raw_uid)
            )
            typ, msg_data = client.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue

            rfc822 = _extract_rfc822(msg_data)
            if rfc822 is None:
                continue

            msg = email.message_from_bytes(rfc822)
            from_header = msg.get("From", "") or ""
            if not sender_matches(from_header, allowed_senders):
                continue

            for filename, payload in iter_attachments_from_message(msg):
                if not extension_allowed(filename, allowed_exts):
                    continue
                yield uid, filename, payload
    finally:
        if owns_connection:
            try:
                client.logout()
            except Exception:
                pass


def _open_client(cfg: MonitorConfig) -> imaplib.IMAP4:
    """按配置建立 SSL 或明文 IMAP 连接。"""
    if cfg.use_ssl:
        return imaplib.IMAP4_SSL(cfg.host, cfg.port)
    return imaplib.IMAP4(cfg.host, cfg.port)


def _extract_rfc822(msg_data: Any) -> Optional[bytes]:
    """从 IMAP FETCH 响应中取出 RFC822 字节。"""
    for item in msg_data:
        if isinstance(item, tuple) and len(item) >= 2:
            payload = item[1]
            if isinstance(payload, (bytes, bytearray)):
                return bytes(payload)
        elif isinstance(item, (bytes, bytearray)):
            # 某些响应片段不是邮件体，跳过
            continue
    return None
