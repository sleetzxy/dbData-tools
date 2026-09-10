"""腾讯企业邮「超大附件」正文链接提取与 HTTP 下载。

超大附件不在 IMAP MIME 里，而是正文中的文件中转站链接。
新版 QQ 邮会把 ``ftnExs_download`` 跳到 SPA 页；真实文件需：

1. 调用 ``/ftn/download?func=3&f=json`` 取文件名与 ``func=4`` 地址；
2. 请求 ``func=4``（不自动跨域跟跳），读取 ``Location`` 与 ``mail5k`` Cookie；
3. 携带 Cookie 下载 ``*.mail.ftn.qq.com`` 直链。
"""

from __future__ import annotations

import json
import logging
import re
from email.header import decode_header, make_header
from email.message import Message
from html import unescape
from typing import Iterator, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

logger = logging.getLogger(__name__)

# 腾讯邮箱 / 企业邮超大附件、中转站常见域名与路径
_FTN_URL_RE = re.compile(
    r"https?://[^\s\"'<>\\]+?(?:"
    r"ftnExs_download|"
    r"/ftn/download|"
    r"ftn\.qq\.com|"
    r"mail\.ftn\.qq\.com|"
    r"dfsdown\.mail\.ftn|"
    r"dfsup\.mail\.ftn|"
    r"exmail\.qq\.com/[^\s\"'<>]*ftn"
    r")[^\s\"'<>\\]*",
    re.IGNORECASE,
)

_ANCHOR_RE = re.compile(
    r"""<a\b[^>]*\bhref\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
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

_FTN_META_HOST = "https://wx.mail.qq.com/ftn/download"


class _NoRedirect(HTTPRedirectHandler):
    """禁止自动跟随跳转，便于跨域时手动带上 Cookie。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _decode_mime_header(raw: Optional[str]) -> str:
    """解码 RFC2047 主题/显示名。"""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


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


def _normalize_url(url: str) -> str:
    """反转义并去掉尾随标点。"""
    return unescape(url).rstrip(").,;]'\"<>")


def _is_ftn_url(url: str) -> bool:
    return bool(_FTN_URL_RE.search(url))


def extract_ftn_download_links(body: str) -> list[str]:
    """从邮件正文提取超大附件 / 中转站下载链接（去重保序）。"""
    return [url for url, _name in extract_ftn_links_with_names(body)]


def extract_ftn_links_with_names(body: str) -> list[tuple[str, str]]:
    """提取 ``(url, 锚文本文件名提示)``，去重保序。"""
    if not body:
        return []
    text = unescape(body)
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    for match in _ANCHOR_RE.finditer(body):
        url = _normalize_url(match.group(1))
        if not _is_ftn_url(url):
            continue
        hint = re.sub(r"<[^>]+>", "", match.group(2))
        hint = unescape(re.sub(r"\s+", " ", hint)).strip()
        if url not in seen:
            seen.add(url)
            found.append((url, hint))

    for match in _FTN_URL_RE.finditer(text):
        url = match.group(0).rstrip(").,;]'\"<>")
        if url not in seen:
            seen.add(url)
            found.append((url, ""))
    return found


def _filename_from_content_disposition(header: Optional[str]) -> str:
    if not header:
        return ""
    # 优先 RFC5987 filename*
    star = re.search(
        r"filename\*\s*=\s*UTF-8''([^;]+)", header, re.IGNORECASE
    )
    if star:
        return unquote(star.group(1).strip().strip('"'))
    match = _FILENAME_RE.search(header)
    if not match:
        return ""
    return unquote(match.group(1).strip().strip("'"))


def _filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("fname", "filename", "name"):
        values = qs.get(key) or []
        if values:
            name = unquote(values[0]).strip()
            if name:
                return name
    path = parsed.path
    name = unquote(path.rsplit("/", 1)[-1] if path else "")
    if name and "." in name and not name.startswith("ftn"):
        return name
    return ""


def _safe_filename(name: str, default: str) -> str:
    cleaned = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return cleaned or default


def _looks_like_html(data: bytes, content_type: Optional[str]) -> bool:
    ctype = (content_type or "").lower()
    if "text/html" in ctype:
        return True
    head = data[:256].lstrip().lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


def _parse_key_code(url: str) -> tuple[str, str]:
    """从中转站链接解析 key/k 与 code。"""
    qs = parse_qs(urlparse(url).query)
    key = (qs.get("key") or qs.get("k") or [""])[0].strip()
    code = (qs.get("code") or [""])[0].strip()
    return key, code


def _is_tencent_ftn_gateway(url: str) -> bool:
    low = url.lower()
    return "ftnexs_download" in low or "/ftn/download" in low


def _cookie_header_from_response(headers: object) -> str:
    get_all = getattr(headers, "get_all", None)
    items = get_all("Set-Cookie") if callable(get_all) else None
    if not items:
        one = headers.get("Set-Cookie")  # type: ignore[attr-defined]
        items = [one] if one else []
    parts = [item.split(";", 1)[0].strip() for item in items if item]
    return "; ".join(p for p in parts if p)


def resolve_tencent_ftn_file(
    url: str,
    *,
    timeout: int = 300,
    default_name: str = "超大附件.bin",
    hint_name: str = "",
) -> tuple[str, bytes]:
    """经 QQ 邮 FTN JSON 接口解析并下载真实文件。

    :param url: 邮件中的 ``ftnExs_download`` / ``/ftn/download`` 链接。
    :param timeout: 超时秒数。
    :param default_name: 默认文件名。
    :param hint_name: 锚文本中的文件名提示。
    :return: ``(filename, content)``。
    """
    key, code = _parse_key_code(url)
    if not key or not code:
        raise ValueError(f"超大附件链接缺少 key/code: {url[:160]}")

    opener = build_opener(_NoRedirect)
    common_headers = {
        "User-Agent": _DEFAULT_UA,
        "Accept": "application/json, */*",
        "Referer": "https://wx.mail.qq.com/",
    }

    meta_url = (
        f"{_FTN_META_HOST}?"
        + urlencode({"func": "3", "key": key, "code": code, "f": "json"})
    )
    with opener.open(
        Request(meta_url, headers=common_headers), timeout=timeout
    ) as meta_resp:
        meta_raw = meta_resp.read()
    try:
        meta = json.loads(meta_raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("超大附件元数据不是合法 JSON") from exc

    head = meta.get("head") or {}
    if int(head.get("ret", -1)) != 0:
        raise ValueError(
            f"超大附件元数据失败 ret={head.get('ret')} msg={head.get('msg')}"
        )
    body = meta.get("body") or {}
    dl_url = str(body.get("url") or "").strip()
    api_name = str(body.get("name") or "").strip()
    if not dl_url:
        raise ValueError("超大附件元数据未返回下载地址")

    # func=4 → Location(dfsdown) + mail5k Cookie（不可丢）
    try:
        opener.open(
            Request(
                dl_url,
                headers={
                    "User-Agent": _DEFAULT_UA,
                    "Accept": "*/*",
                    "Referer": meta_url,
                },
            ),
            timeout=timeout,
        )
        raise ValueError("超大附件 func=4 未返回跳转地址")
    except HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        location = exc.headers.get("Location")
        cookie = _cookie_header_from_response(exc.headers)
        if not location:
            raise ValueError("超大附件 func=4 缺少 Location") from exc

    file_headers = {
        "User-Agent": _DEFAULT_UA,
        "Accept": "*/*",
        "Referer": "https://wx.mail.qq.com/",
    }
    if cookie:
        file_headers["Cookie"] = cookie

    with opener.open(
        Request(location, headers=file_headers), timeout=timeout
    ) as file_resp:
        data = file_resp.read()
        ctype = file_resp.headers.get("Content-Type")
        cdisp = file_resp.headers.get("Content-Disposition")

    if not data:
        raise ValueError("超大附件下载内容为空")
    if _looks_like_html(data, ctype):
        raise ValueError(
            "超大附件下载到 HTML 中间页（可能缺 Cookie 或链接失效）"
        )

    filename = _safe_filename(
        api_name
        or hint_name
        or _filename_from_content_disposition(cdisp)
        or _filename_from_url(location)
        or default_name,
        default_name,
    )
    return filename, data


def download_http_file(
    url: str,
    *,
    timeout: int = 300,
    default_name: str = "超大附件.bin",
    hint_name: str = "",
) -> tuple[str, bytes]:
    """下载超大附件链接，返回 ``(filename, content)``。

    腾讯网关链接走 FTN JSON 解析；其它直链直接 HTTP GET。
    """
    if _is_tencent_ftn_gateway(url):
        return resolve_tencent_ftn_file(
            url,
            timeout=timeout,
            default_name=default_name,
            hint_name=hint_name,
        )

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
        ctype = response.headers.get("Content-Type")
        if _looks_like_html(data, ctype):
            raise ValueError(f"超大附件下载到 HTML 而非文件: {url[:160]}")
        header_name = _filename_from_content_disposition(
            response.headers.get("Content-Disposition")
        )
        filename = _safe_filename(
            hint_name
            or header_name
            or _filename_from_url(url)
            or default_name,
            default_name,
        )
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
    links = extract_ftn_links_with_names(body)
    if not links:
        return

    subject = _decode_mime_header(msg.get("Subject", "") or "")
    log.info("发现超大附件链接 %s 个（主题=%s）", len(links), subject)

    for index, (url, hint_name) in enumerate(links, start=1):
        default_name = f"超大附件_{index}.bin"
        try:
            filename, payload = download_http_file(
                url,
                timeout=timeout,
                default_name=default_name,
                hint_name=hint_name,
            )
            log.info(
                "超大附件下载成功：%s（%s 字节）",
                filename,
                len(payload),
            )
            yield filename, payload
        except (HTTPError, URLError, OSError, ValueError, TimeoutError) as exc:
            log.warning("超大附件下载失败：%s — %s", url[:200], exc)
