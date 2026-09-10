"""邮件监控发件人与附件扩展名过滤。"""

from __future__ import annotations

import re
from email.utils import parseaddr


def parse_sender_list(raw: str) -> set[str]:
    """按逗号或换行拆分发件人列表，去空白并转为小写。"""
    if not raw.strip():
        return set()
    parts = re.split(r"[,;\n]+", raw)
    return {part.strip().lower() for part in parts if part.strip()}


def sender_matches(from_header: str, allowed: set[str]) -> bool:
    """判断发件人是否在允许列表中（忽略显示名与大小写）。"""
    _, address = parseaddr(from_header)
    if not address:
        return False
    return address.lower() in allowed


def normalize_extensions(raw: str) -> set[str]:
    """规范化扩展名：补前导点、小写；空输入返回空集合。"""
    if not raw.strip():
        return set()
    parts = re.split(r"[,;\n]+", raw)
    result: set[str] = set()
    for part in parts:
        ext = part.strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = f".{ext}"
        result.add(ext)
    return result


def extension_allowed(filename: str, allowed: set[str]) -> bool:
    """空白名单不允许任何文件；否则按扩展名精确匹配（大小写不敏感）。"""
    if not allowed:
        return False
    dot = filename.rfind(".")
    if dot < 0:
        return False
    ext = filename[dot:].lower()
    return ext in allowed
