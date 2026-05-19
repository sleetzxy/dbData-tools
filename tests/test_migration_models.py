"""Tests for migration models (dataclasses)."""

from __future__ import annotations

from core.migration.models import (
    ChunkProgress,
    ChunkSpec,
    MigrationCondition,
    MigrationMeta,
    TableMigrationResult,
)


def test_migration_condition_defaults() -> None:
    """Verify MigrationCondition default values."""
    cond = MigrationCondition(table_name="users", mode="where")
    assert cond.table_name == "users"
    assert cond.mode == "where"
    assert cond.where_clause == ""
    assert cond.custom_sql == ""
    assert cond.chunk_key == ""
    assert cond.chunk_size == 100_000
    assert cond.enabled is True


def test_migration_condition_field_types() -> None:
    """Verify field type constraints via construction."""
    cond = MigrationCondition(
        table_name="orders",
        mode="sql",
        where_clause="status = 'active'",
        custom_sql="SELECT * FROM orders",
        chunk_key="order_id",
        chunk_size=5000,
        enabled=False,
    )
    assert cond.table_name == "orders"
    assert cond.mode == "sql"
    assert cond.where_clause == "status = 'active'"
    assert cond.custom_sql == "SELECT * FROM orders"
    assert cond.chunk_key == "order_id"
    assert cond.chunk_size == 5000
    assert cond.enabled is False


def test_chunk_spec_with_none_bounds() -> None:
    """ChunkSpec can be created with None key_start and key_end."""
    spec = ChunkSpec(chunk_index=0, key_start=None, key_end=None)
    assert spec.chunk_index == 0
    assert spec.key_start is None
    assert spec.key_end is None


def test_chunk_spec_with_values() -> None:
    """ChunkSpec with integer bounds."""
    spec = ChunkSpec(chunk_index=2, key_start=100, key_end=200)
    assert spec.chunk_index == 2
    assert spec.key_start == 100
    assert spec.key_end == 200


def test_table_migration_result_success() -> None:
    """TableMigrationResult for a successful migration."""
    result = TableMigrationResult(
        table_name="users",
        success=True,
        total_rows=5000,
        total_chunks=5,
        completed_chunks=5,
    )
    assert result.table_name == "users"
    assert result.success is True
    assert result.total_rows == 5000
    assert result.total_chunks == 5
    assert result.completed_chunks == 5
    assert result.error == ""


def test_table_migration_result_error() -> None:
    """TableMigrationResult for a failed migration."""
    result = TableMigrationResult(
        table_name="orders",
        success=False,
        total_rows=3000,
        total_chunks=3,
        completed_chunks=2,
        error="chunk 2 failed: timeout",
    )
    assert result.table_name == "orders"
    assert result.success is False
    assert result.total_rows == 3000
    assert result.total_chunks == 3
    assert result.completed_chunks == 2
    assert result.error == "chunk 2 failed: timeout"


def test_chunk_progress_fields() -> None:
    """Verify ChunkProgress stores all field values."""
    progress = ChunkProgress(
        table_name="users",
        chunk_index=1,
        total_table_chunks=5,
        total_across_all_tables=10,
        completed_across_all_tables=3,
        rows=1000,
    )
    assert progress.table_name == "users"
    assert progress.chunk_index == 1
    assert progress.total_table_chunks == 5
    assert progress.total_across_all_tables == 10
    assert progress.completed_across_all_tables == 3
    assert progress.rows == 1000


def test_migration_meta_default_factory() -> None:
    """MigrationMeta.completed_chunks default is an empty dict."""
    meta = MigrationMeta(migration_id="test-1", tables=[])
    assert meta.migration_id == "test-1"
    assert meta.tables == []
    assert meta.completed_chunks == {}
    assert meta.created_at == ""


def test_migration_meta_with_completed_chunks() -> None:
    """MigrationMeta stores completed_chunks as dict[str, set[int]]."""
    meta = MigrationMeta(
        migration_id="test-2",
        tables=[
            MigrationCondition(table_name="users", mode="where"),
        ],
        completed_chunks={
            "users": {0, 1, 2},
            "orders": {0},
        },
    )
    assert meta.completed_chunks["users"] == {0, 1, 2}
    assert meta.completed_chunks["orders"] == {0}
    assert meta.migration_id == "test-2"
    assert len(meta.tables) == 1
