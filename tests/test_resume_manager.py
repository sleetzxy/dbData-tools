"""Tests for ResumeManager: save, load, delete, update_progress, list_incomplete."""

from __future__ import annotations

import json
import os

import pytest

from core.migration.models import MigrationCondition, MigrationMeta
from core.migration.resume_manager import ResumeManager


@pytest.fixture
def manager(tmp_path: pytest.TempPathFactory) -> ResumeManager:
    return ResumeManager(resume_dir=str(tmp_path))


def _make_meta(
    migration_id: str = "test-mig-001",
    tables: list[MigrationCondition] | None = None,
) -> MigrationMeta:
    if tables is None:
        tables = [
            MigrationCondition(table_name="users", mode="where"),
        ]
    return MigrationMeta(migration_id=migration_id, tables=tables)


def test_save_and_load(manager: ResumeManager) -> None:
    """save writes JSON, load returns identical data."""
    meta = _make_meta()
    path = manager.save(meta)
    assert os.path.isfile(path)

    loaded = manager.load(meta.migration_id)
    assert loaded is not None
    assert loaded.migration_id == meta.migration_id
    assert len(loaded.tables) == len(meta.tables)
    assert loaded.tables[0].table_name == meta.tables[0].table_name


def test_load_nonexistent_returns_none(manager: ResumeManager) -> None:
    result = manager.load("does-not-exist")
    assert result is None


def test_load_corrupted_json_returns_none(manager: ResumeManager) -> None:
    """Corrupted JSON file is silently skipped."""
    meta = _make_meta()
    path = manager.save(meta)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{invalid json}")

    loaded = manager.load(meta.migration_id)
    assert loaded is None


def test_load_missing_keys_returns_none(manager: ResumeManager) -> None:
    """JSON missing required keys is silently skipped."""
    meta = _make_meta()
    path = manager.save(meta)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"migration_id": "orphan"}, f)

    loaded = manager.load(meta.migration_id)
    assert loaded is None


def test_delete_removes_file(manager: ResumeManager) -> None:
    meta = _make_meta()
    path = manager.save(meta)
    assert os.path.isfile(path)

    manager.delete(meta.migration_id)
    assert not os.path.isfile(path)


def test_delete_nonexistent_does_not_raise(manager: ResumeManager) -> None:
    manager.delete("non-existent")  # Should not raise


def test_update_progress_adds_chunk(manager: ResumeManager) -> None:
    """update_progress adds chunk_index and persists to disk."""
    meta = _make_meta()
    manager.save(meta)

    manager.update_progress("test-mig-001", "users", 0)
    loaded = manager.load("test-mig-001")
    assert loaded is not None
    assert 0 in loaded.completed_chunks["users"]

    manager.update_progress("test-mig-001", "users", 1)
    loaded = manager.load("test-mig-001")
    assert loaded is not None
    assert loaded.completed_chunks["users"] == {0, 1}


def test_update_progress_no_meta_does_not_raise(
    manager: ResumeManager,
) -> None:
    """update_progress on non-existent migration logs a warning and returns."""
    manager.update_progress("non-existent", "users", 0)  # Should not raise


def test_list_incomplete_returns_incomplete(manager: ResumeManager) -> None:
    """list_incomplete returns saved migrations."""
    meta1 = _make_meta(migration_id="mig-001")
    meta2 = _make_meta(
        migration_id="mig-002",
        tables=[MigrationCondition(table_name="orders", mode="where")],
    )
    manager.save(meta1)
    manager.save(meta2)

    incomplete = manager.list_incomplete()
    ids = {m.migration_id for m in incomplete}
    assert "mig-001" in ids
    assert "mig-002" in ids


def test_list_incomplete_skips_corrupted(manager: ResumeManager) -> None:
    """list_incomplete silently skips corrupted JSON files."""
    meta = _make_meta(migration_id="good-mig")
    manager.save(meta)

    # Create a corrupted file
    with open(os.path.join(manager.resume_dir, "bad-mig.json"), "w") as f:
        f.write("garbage data")

    incomplete = manager.list_incomplete()
    ids = [m.migration_id for m in incomplete]
    assert "good-mig" in ids
    assert "bad-mig" not in ids  # Not a valid MigrationMeta


@pytest.mark.parametrize("unsafe_id", [
    "../etc/passwd",
    "foo/bar",
    "",
])
def test_unsafe_migration_id_raises_value_error(
    manager: ResumeManager,
    unsafe_id: str,
) -> None:
    with pytest.raises(ValueError, match="不安全的 migration_id"):
        manager._file_path(unsafe_id)


def test_multiple_tables_with_multiple_chunks(manager: ResumeManager) -> None:
    """Multiple tables each track their own completed chunks."""
    meta = MigrationMeta(
        migration_id="multi-table",
        tables=[
            MigrationCondition(table_name="users", mode="where"),
            MigrationCondition(table_name="orders", mode="where"),
            MigrationCondition(table_name="items", mode="where"),
        ],
    )
    manager.save(meta)

    for table in ["users", "orders", "items"]:
        for chunk_idx in range(5):
            manager.update_progress("multi-table", table, chunk_idx)

    loaded = manager.load("multi-table")
    assert loaded is not None
    assert loaded.completed_chunks["users"] == {0, 1, 2, 3, 4}
    assert loaded.completed_chunks["orders"] == {0, 1, 2, 3, 4}
    assert loaded.completed_chunks["items"] == {0, 1, 2, 3, 4}
