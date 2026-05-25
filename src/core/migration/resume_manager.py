"""断点续传管理器：将迁移断点保存为本地 JSON 文件。"""

from __future__ import annotations

import dataclasses
import glob
import json
import logging
import os
import re
from typing import Any

from core.migration.models import (
    MigrationCondition,
    MigrationMeta,
)

logger = logging.getLogger("migrate.resume")

_RESUME_SUBDIR = ".db_migrator_resume"
_MIGRATION_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _validate_migration_id(migration_id: str) -> str:
    """验证 migration_id 只包含安全字符，防止路径遍历。"""
    if not migration_id or not _MIGRATION_ID_RE.match(migration_id):
        raise ValueError(f"不安全的 migration_id: {migration_id!r}")
    return migration_id


def _meta_to_dict(meta: MigrationMeta) -> dict[str, Any]:
    """将 MigrationMeta 转换为 JSON 可序列化的字典。

    set 在 JSON 中没有对应类型，转为有序列表存储。
    """
    return {
        "migration_id": meta.migration_id,
        "tables": [dataclasses.asdict(t) for t in meta.tables],
        "completed_chunks": {
            k: sorted(v) for k, v in meta.completed_chunks.items()
        },
        "chunk_labels": meta.chunk_labels,
        "created_at": meta.created_at,
    }


def _dict_to_meta(data: dict[str, Any]) -> MigrationMeta:
    """将字典还原为 MigrationMeta。

    JSON 中存储的列表重新转为 set。
    """
    return MigrationMeta(
        migration_id=data["migration_id"],
        tables=[MigrationCondition(**t) for t in data["tables"]],
        completed_chunks={
            k: set(v) for k, v in data["completed_chunks"].items()
        },
        chunk_labels={
            k: {int(idx): label for idx, label in v.items()}
            for k, v in data.get("chunk_labels", {}).items()
        },
        created_at=data["created_at"],
    )


class ResumeManager:
    """管理迁移断点文件的读写与清理。"""

    def __init__(self, resume_dir: str | None = None) -> None:
        self.resume_dir = resume_dir or os.path.join(
            os.path.expanduser("~"), _RESUME_SUBDIR
        )

    def _file_path(self, migration_id: str) -> str:
        _validate_migration_id(migration_id)
        return os.path.join(self.resume_dir, f"{migration_id}.json")

    def save(self, meta: MigrationMeta) -> str:
        """将迁移断点写入 JSON 文件。"""
        os.makedirs(self.resume_dir, exist_ok=True)
        path = self._file_path(meta.migration_id)
        data = _meta_to_dict(meta)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, default=str, indent=2, ensure_ascii=False)
        logger.info("断点已保存: %s", path)
        return path

    def load(self, migration_id: str) -> MigrationMeta | None:
        """从文件中加载迁移断点。文件不存在或损坏时返回 None。"""
        path = self._file_path(migration_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            meta = _dict_to_meta(data)
            logger.info("断点已加载: %s", path)
            return meta
        except (json.JSONDecodeError, KeyError, TypeError, OSError) as exc:
            logger.warning("断点文件损坏，跳过: %s, 错误: %s", path, exc)
            return None

    def delete(self, migration_id: str) -> None:
        """迁移成功后删除断点文件。"""
        path = self._file_path(migration_id)
        if os.path.isfile(path):
            os.remove(path)
            logger.info("断点已删除: %s", path)

    def list_incomplete(self) -> list[MigrationMeta]:
        """列出 resume_dir 下所有未完成的迁移断点。"""
        pattern = os.path.join(self.resume_dir, "*.json")
        results: list[MigrationMeta] = []
        for path in sorted(glob.glob(pattern)):
            migration_id = os.path.splitext(os.path.basename(path))[0]
            meta = self.load(migration_id)
            if meta is not None:
                results.append(meta)
        return results

    def update_progress(
        self, migration_id: str, table_name: str, chunk_index: int
    ) -> None:
        """标记指定分块已完成并写回文件。"""
        meta = self.load(migration_id)
        if meta is None:
            logger.warning("未找到迁移断点 %s，无法更新进度", migration_id)
            return
        completed = meta.completed_chunks.setdefault(table_name, set())
        completed.add(chunk_index)
        self.save(meta)
