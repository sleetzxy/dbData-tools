"""附件去重键生成与持久化存储。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def make_dedup_key(account: str, mailbox_uid: str, filename: str) -> str:
    """生成附件去重键。

    格式：``account|mailbox_uid|filename``

    :param account: 邮箱账号。
    :param mailbox_uid: 邮件 UID。
    :param filename: 附件文件名。
    :return: 去重键字符串。
    """
    return f"{account}|{mailbox_uid}|{filename}"


class DedupStore:
    """已处理附件去重键的 JSON 持久化存储。"""

    def __init__(self, path: Path) -> None:
        """加载或初始化去重存储。

        :param path: JSON 文件路径。
        """
        self._path = path
        self._seen: set[str] = self._load()

    def has(self, key: str) -> bool:
        """检查去重键是否已存在。

        :param key: 去重键。
        :return: 已存在返回 ``True``。
        """
        return key in self._seen

    def add(self, key: str) -> None:
        """记录去重键并立即落盘。

        :param key: 去重键。
        """
        self._seen.add(key)
        self._save()

    def _load(self) -> set[str]:
        """从 JSON 文件加载去重键集合；损坏时当作空集。"""
        if not self._path.exists():
            return set()

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("去重存储文件损坏或无法读取，当作空集: %s", exc)
            return set()

        if not isinstance(data, list):
            logger.warning("去重存储文件格式无效，当作空集")
            return set()

        return set(data)

    def _save(self) -> None:
        """将去重键集合写入 JSON 文件。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(sorted(self._seen), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
