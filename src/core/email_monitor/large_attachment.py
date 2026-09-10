"""腾讯企业邮「超大附件」正文链接提取与 HTTP 下载。

超大附件不在 IMAP MIME 里，而是正文中的文件中转站链接。
"""

from __future__ import annotations

import logging
import re
from email.message import Message
from html import unescape
from typing import Iterator, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# 腾讯邮箱 / 企业邮超大附件、中转站常见域名与路径
_FTN_URL_RE = re.compile(
    r"https?://[^\s\"'<>\\]+?(?:"
    r"ftnExs_download|"
    r"ftn\.qq\.com|"
    r"mail\.ftn\.qq\.com|"
    r"dfsdown\.mail\.ftn|"
    r"dfsup\.mail\.ftn|"
    r"exmail\.qq\.com/[^\s\"'<>]*ftn"
    r")[^\s\"'<>\\]*",
    re.IGNORECASE,
)

# Content-Disposition: attachment; filename="xxx.zip"
_FILENAME_RE = re.compile(
    r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?',
    re.IGNORECASE,
)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def collect_message_text(msg: Message) -> str:
    """拼接邮件 text/plain 与 text/html 正文，供提取链接。"""
    chunks: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                chunks.append(payload.decode(charset, errors="replace"))
            except LookupError:
                chunks.append(payload.decode("utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                chunks.append(payload.decode(charset, errors="replace"))
            except LookupError:
                chunks.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def extract_ftn_download_links(body: str) -> list[str]:
    """从邮件正文提取超大附件 / 中转站下载链接（去重保序）。"""
    if not body:
        return []
    text = unescape(body)
    # HTML 中 &amp; 已 unescape；去掉常见尾随标点
    found: list[str] = []
    seen: set[str] = set()
    for match in _FTN_URL_RE.finditer(text):
        url = match.group(0).rstrip(").,;]'\"<>")
        if url not in seen:
            seen.add(url)
            found.append(url)
    return found


def _filename_from_content_disposition(header: Optional[str]) -> str:
    if not header:
        return ""
    match = _FILENAME_RE.search(header)
    if not match:
        return ""
    name = unquote(match.group(1).strip().strip("'"))
    return name


def _filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = unquote(path.rsplit("/", 1)[-1] if path else "")
    if name and "." in name and not name.startswith("ftn"):
        return name
    return ""


def download_http_file(
    url: str,
    *,
    timeout: int = 300,
    default_name: str = "超大附件.bin",
) -> tuple[str, bytes]:
    """HTTP 下载超大附件链接，返回 ``(filename, content)``。

    :param url: 中转站下载地址。
    :param timeout: 超时秒数（大文件需较长）。
    :param default_name: 无法解析文件名时的默认名。
    :raises URLError, HTTPError, OSError, ValueError: 下载失败。
    """
    request = Request(
        url,
        headers={
            "User-Agent": _DEFAULT_UA,
            "Accept": "*/*",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
        if not data:
            raise ValueError(f"超大附件下载内容为空: {url}")
        header_name = _filename_from_content_disposition(
            response.headers.get("Content-Disposition")
        )
        filename = header_name or _filename_from_url(url) or default_name
        # 去掉路径分隔，防止穿越
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        return filename, data


def iter_large_attachments_from_message(
    msg: Message,
    *,
    log: Optional[logging.Logger] = None,
    timeout: int = 300,
) -> Iterator[tuple[str, bytes]]:
    """从邮件正文超大附件链接下载文件。

    :param msg: 邮件消息。
    :param log: 可选日志器。
    :param timeout: 单文件下载超时。
    :return: ``(filename, payload_bytes)``。
    """
    log = log or logger
    body = collect_message_text(msg)
    links = extract_ftn_download_links(body)
    if not links:
        return

    subject = msg.get("Subject", "") or ""
    log.info("发现超大附件链接 %s 个（主题=%s）", len(links), subject)

    for index, url in enumerate(links, start=1):
        default_name = f"超大附件_{index}.bin"
        try:
            filename, payload = download_http_file(
                url, timeout=timeout, default_name=default_name
            )
            log.info(
                "超大附件下载成功：%s（%s 字节） url=%s",
                filename,
                len(payload),
                url[:120],
            )
            yield filename, payload
        except (HTTPError, URLError, OSError, ValueError, TimeoutError) as exc:
            log.warning("超大附件下载失败：%s — %s", url[:160], exc)
