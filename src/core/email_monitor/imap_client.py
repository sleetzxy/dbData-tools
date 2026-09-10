"""IMAP 连接、检索与附件解析（标准库，可注入 mock）。"""

from __future__ import annotations

import email
import imaplib
import logging
from datetime import date, timedelta
from email.header import decode_header, make_header
from email.message import Message
from typing import Any, Iterator, Optional

from core.email_monitor.filters import (
    extension_allowed,
    normalize_extensions,
    sender_matches,
)
from core.email_monitor.models import MonitorConfig

logger = logging.getLogger(__name__)

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


def _decode_mime_filename(raw: Optional[str]) -> str:
    """解码 MIME 文件名（兼容 RFC2047 编码的中文名）。"""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def iter_attachments_from_message(msg: Message) -> Iterator[tuple[str, bytes]]:
    """从 MIME 消息中提取附件（文件名, 内容）。

    规则：``Content-Disposition: attachment``、带 filename/name 的 part；
    跳过纯内联图片。

    :param msg: 已解析的邮件消息。
    :return: ``(filename, payload_bytes)`` 迭代器。
    """
    for part in msg.walk():
        if part.is_multipart():
            continue

        disposition = (part.get_content_disposition() or "").lower()
        maintype = part.get_content_maintype()
        subtype = (part.get_content_subtype() or "").lower()
        filename = _decode_mime_filename(part.get_filename())
        if not filename:
            # 部分客户端只在 Content-Type 的 name 参数放文件名
            filename = _decode_mime_filename(part.get_param("name"))

        # 跳过纯内联图 / 签名图
        if disposition == "inline" and maintype == "image":
            continue

        if disposition != "attachment" and not filename:
            continue

        if not filename:
            filename = f"attachment.{subtype or 'bin'}"

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


def _message_sender_candidates(msg: Message) -> list[str]:
    """收集可用于匹配的发件相关头（From / Sender / Reply-To）。"""
    headers: list[str] = []
    for key in ("From", "Sender", "Reply-To"):
        value = msg.get(key, "") or ""
        if value:
            headers.append(value)
    return headers


def iter_matching_attachments(
    cfg: MonitorConfig,
    imap: Optional[Any] = None,
    log: Optional[logging.Logger] = None,
) -> Iterator[tuple[str, str, bytes]]:
    """检索匹配发件人与扩展名白名单的附件。

    必须使用 ``UID SEARCH`` / ``UID FETCH``，yield 的 uid 为 IMAP UID。

    :param cfg: 监控配置。
    :param imap: 可选已连接的 IMAP 对象（便于单测注入）；为 ``None`` 时自行连接。
    :param log: 可选日志器（GUI 页传入时诊断信息会出现在右侧面板）。
    :return: ``(uid, filename, payload_bytes)`` 迭代器。
    """
    log = log or logger
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
            log.info(
                "IMAP 检索无结果：SINCE %s（请确认邮件在收件箱且日期在范围内）",
                since,
            )
            return

        uid_bytes = data[0]
        if isinstance(uid_bytes, int):
            return
        raw_uids = uid_bytes.split()
        if not raw_uids:
            log.info("IMAP SINCE %s 命中 0 封邮件", since)
            return

        allowed_senders = {s.strip().lower() for s in cfg.senders if s.strip()}
        allowed_exts = normalize_extensions(",".join(cfg.extensions))
        log.info(
            "开始扫描：SINCE %s，收件箱命中 %s 封；发件人=%s；扩展名=%s",
            since,
            len(raw_uids),
            sorted(allowed_senders),
            sorted(allowed_exts),
        )

        matched_sender = 0
        matched_attach = 0
        skipped_ext = 0

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
            candidates = _message_sender_candidates(msg)
            if not any(sender_matches(h, allowed_senders) for h in candidates):
                continue
            matched_sender += 1

            yielded_for_mail = False
            for filename, payload in iter_attachments_from_message(msg):
                if not extension_allowed(filename, allowed_exts):
                    skipped_ext += 1
                    log.info(
                        "跳过扩展名不匹配附件：uid=%s filename=%s allowed=%s",
                        uid,
                        filename,
                        sorted(allowed_exts),
                    )
                    continue
                matched_attach += 1
                yielded_for_mail = True
                yield uid, filename, payload

            if not yielded_for_mail:
                log.info(
                    "发件人已匹配但无可用附件：uid=%s From=%s",
                    uid,
                    msg.get("From", ""),
                )

        log.info(
            "扫描汇总：发件人匹配 %s 封，产出附件 %s，扩展名跳过 %s",
            matched_sender,
            matched_attach,
            skipped_ext,
        )
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
    """从 UID FETCH 返回结构中提取 RFC822 字节。"""
    if not msg_data:
        return None
    for item in msg_data:
        if isinstance(item, tuple) and len(item) >= 2:
            payload = item[1]
            if isinstance(payload, (bytes, bytearray)):
                return bytes(payload)
    return None
