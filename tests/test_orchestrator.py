"""Tests for MigrationOrchestrator: chunk loop, retry, resume, progress, truncate."""

from __future__ import annotations

import os
from typing import Any

import pytest

from core.migration.models import (
    ChunkProgress,
    ChunkSpec,
    MigrationCondition,
    MigrationMeta,
    TransferMode,
)
from core.migration.orchestrator import MigrationOrchestrator

_FAKE_CHUNKS = [
    ChunkSpec(chunk_index=0, key_start=0, key_end=100),
    ChunkSpec(chunk_index=1, key_start=100, key_end=200),
    ChunkSpec(chunk_index=2, key_start=200, key_end=300),
]


class _MockOrchAdapter:
    """Mock adapter that tracks calls and simulates configurable failures."""

    db_type = "postgresql"

    def __init__(
        self,
        fail_chunks: dict[tuple[str, int], int] | None = None,
    ) -> None:
        self.export_calls: list[tuple[str, int | None]] = []
        self.import_calls: list[tuple[list[str], bool]] = []
        # {(table, chunk_start): remaining_fail_count}
        self.fail_chunks: dict[tuple[str, int], int] = (
            dict(fail_chunks) if fail_chunks else {}
        )

    def create_client(self, config: dict[str, Any]) -> object:
        return object()

    def close_client(self, client: object) -> None:
        pass

    def export_csv(
        self,
        client: object,
        db_config: dict[str, Any],
        table: str,
        export_dir: str,
        schema: str = "",
        include_header: bool = True,
        where_clause: str = "",
        custom_sql: str = "",
        chunk_key: str = "",
        chunk_start: int | None = None,
        chunk_end: int | None = None,
        logger: Any = None,
    ) -> dict[str, Any]:
        key = (table, chunk_start)
        self.export_calls.append((table, chunk_start))

        # Simulate configurable failures
        if key in self.fail_chunks and self.fail_chunks[key] > 0:
            self.fail_chunks[key] -= 1
            return {"success": False, "error": "mock export fail"}

        # Write the CSV file so the orchestrator finds it
        csv_dir = os.path.join(export_dir, table, f"chunk_{0:06d}")
        os.makedirs(csv_dir, exist_ok=True)
        csv_path = os.path.join(export_dir, f"{table}.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("id,val\n1,x\n")
        return {"success": True, "total_rows": 1, "exported_tables": []}

    def import_csv(
        self,
        client: object,
        db_config: dict[str, Any],
        table_names: list[str],
        data_dir: str,
        schema: str = "",
        pre_sql_file: str = "",
        need_backup: bool = False,
        truncate_before: bool = True,
        is_first_chunk: bool = False,
        logger: Any = None,
    ) -> dict[str, Any]:
        self.import_calls.append((table_names, is_first_chunk))
        return {"success": True, "imported_tables": table_names, "error_tables": []}

    # ------------------------------------------------------------------
    # Stream methods (needed when orchestrator uses default STREAM mode)
    # ------------------------------------------------------------------

    def _build_chunked_query(
        self,
        table: str,
        schema: str = "",
        where_clause: str = "",
        custom_sql: str = "",
        chunk_key: str = "",
        chunk_start: Any = None,
        chunk_end: Any = None,
    ) -> Any:
        class _Query:
            def as_string(self, client: Any) -> str:
                return f"SELECT * FROM {table}"
        return _Query()

    def get_table_columns(
        self, client: Any, table_name: str, schema: str = "",
    ) -> list[str]:
        return ["id", "val"]

    def copy_stream_transfer(
        self,
        src_client: Any,
        dst_client: Any,
        src_query: str,
        dst_table: str,
        columns: list[str],
        schema: str = "",
    ) -> int:
        return 1


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_orchestrator() -> Any:
    """Factory fixture for quick orchestrator creation."""

    def _build(
        conditions: list[MigrationCondition] | None = None,
        truncate_before: bool = True,
        resume_from: str | None = None,
        progress_callback: Any = None,
        src_adapter: Any = None,
        dst_adapter: Any = None,
        transfer_mode: TransferMode = TransferMode.CSV,
    ) -> MigrationOrchestrator:
        if conditions is None:
            conditions = [
                MigrationCondition(
                    table_name="test_table",
                    mode="where",
                    chunk_key="id",
                    chunk_size=100,
                ),
            ]
        if src_adapter is None:
            src_adapter = _MockOrchAdapter()
        if dst_adapter is None:
            dst_adapter = _MockOrchAdapter()

        return MigrationOrchestrator(
            src_config={
                "db_type": "postgresql",
                "host": "localhost",
                "port": 5432,
                "database": "src_db",
                "user": "u",
                "password": "p",
                "schema": "public",
            },
            dst_config={
                "db_type": "postgresql",
                "host": "localhost",
                "port": 5432,
                "database": "dst_db",
                "user": "u",
                "password": "p",
                "schema": "public",
            },
            conditions=conditions,
            truncate_before=truncate_before,
            resume_from=resume_from,
            progress_callback=progress_callback,
            src_adapter=src_adapter,
            dst_adapter=dst_adapter,
            transfer_mode=transfer_mode,
        )

    return _build


# ---------------------------------------------------------------------------
# Basic migration
# ---------------------------------------------------------------------------


def test_basic_migration_single_table(
    mocker: Any,
    make_orchestrator: Any,
) -> None:
    """1 table, 3 chunks — all succeed."""
    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=_FAKE_CHUNKS,
    )
    src_adapter = _MockOrchAdapter()
    dst_adapter = _MockOrchAdapter()
    orch = make_orchestrator(
        src_adapter=src_adapter,
        dst_adapter=dst_adapter,
    )
    result = orch.run()

    assert result["success"] is True
    assert len(result["migrated_tables"]) == 1
    assert result["migrated_tables"][0]["name"] == "test_table"
    assert result["total_rows"] == 3  # 1 row per chunk
    assert result["error_tables"] == []
    # 3 export calls, 3 import calls
    assert len(src_adapter.export_calls) == 3
    assert len(dst_adapter.import_calls) == 3


def test_multi_table_migration(
    mocker: Any,
    make_orchestrator: Any,
) -> None:
    """2 tables, 3 chunks each — both succeed."""
    conditions = [
        MigrationCondition(
            table_name="table_a",
            mode="where",
            chunk_key="id",
            chunk_size=100,
        ),
        MigrationCondition(
            table_name="table_b",
            mode="where",
            chunk_key="id",
            chunk_size=100,
        ),
    ]
    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=_FAKE_CHUNKS,
    )
    adapter = _MockOrchAdapter()
    orch = make_orchestrator(
        conditions=conditions,
        src_adapter=adapter,
        dst_adapter=adapter,
    )
    result = orch.run()

    assert result["success"] is True
    assert len(result["migrated_tables"]) == 2
    # 6 exports (3 per table), 6 imports (3 per table)
    assert len(adapter.export_calls) == 6
    assert len(adapter.import_calls) == 6


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def test_chunk_failure_with_retry(
    mocker: Any,
    make_orchestrator: Any,
) -> None:
    """A chunk fails once then succeeds on retry."""
    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=_FAKE_CHUNKS,
    )
    mocker.patch("core.migration.orchestrator.time.sleep")

    src_adapter = _MockOrchAdapter(
        fail_chunks={("test_table", 0): 1},  # chunk 0 fails once
    )
    dst_adapter = _MockOrchAdapter()
    orch = make_orchestrator(
        src_adapter=src_adapter,
        dst_adapter=dst_adapter,
    )
    result = orch.run()

    assert result["success"] is True
    # 4 export calls = 1 fail + 1 success (chunk 0) + 1 + 1 (chunks 1, 2)
    assert len(src_adapter.export_calls) == 4
    assert len(dst_adapter.import_calls) == 3


def test_chunk_failure_exhausts_retries(
    mocker: Any,
    make_orchestrator: Any,
) -> None:
    """A chunk fails all 4 attempts (0 + 3 retries), table marked as partial failure."""
    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=_FAKE_CHUNKS,
    )
    mocker.patch("core.migration.orchestrator.time.sleep")

    src_adapter = _MockOrchAdapter(
        fail_chunks={("test_table", 0): 4},  # chunk 0 fails all 4 attempts
    )
    dst_adapter = _MockOrchAdapter()
    orch = make_orchestrator(
        src_adapter=src_adapter,
        dst_adapter=dst_adapter,
    )
    result = orch.run()

    # Table should be marked as failed but migration continues
    assert result["success"] is False
    assert len(result["error_tables"]) == 1
    assert result["error_tables"][0]["name"] == "test_table"
    # Only chunks 1, 2 should have been imported (chunk 0 never succeeded)
    assert len(dst_adapter.import_calls) == 2


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------


def test_progress_callback_called(
    mocker: Any,
    make_orchestrator: Any,
) -> None:
    """Progress callback is invoked for each successfully migrated chunk."""
    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=_FAKE_CHUNKS,
    )

    callback = mocker.Mock()
    adapter = _MockOrchAdapter()
    orch = make_orchestrator(
        src_adapter=adapter,
        dst_adapter=adapter,
        progress_callback=callback,
    )
    orch.run()

    # Callback should be called 3 times (one per chunk)
    assert callback.call_count == 3
    calls = callback.call_args_list
    for i, call in enumerate(calls):
        progress: ChunkProgress = call[0][0]
        assert progress.table_name == "test_table"
        assert progress.chunk_index == i
        assert progress.total_table_chunks == 3
        assert progress.total_across_all_tables == 3
        assert progress.rows == 1


# ---------------------------------------------------------------------------
# _resolve_truncate
# ---------------------------------------------------------------------------


def test_resolve_truncate_first_chunk(
    make_orchestrator: Any,
) -> None:
    """First chunk of a fresh migration with truncate_before=True truncates."""
    orch = make_orchestrator(truncate_before=True, resume_from=None)
    assert orch._resolve_truncate(is_first_chunk=True) is True


def test_resolve_truncate_subsequent_chunk(
    make_orchestrator: Any,
) -> None:
    """Subsequent chunks do not truncate."""
    orch = make_orchestrator(truncate_before=True, resume_from=None)
    assert orch._resolve_truncate(is_first_chunk=False) is False


def test_resolve_truncate_resume_mode(
    make_orchestrator: Any,
) -> None:
    """Resume mode never truncates."""
    orch = make_orchestrator(
        truncate_before=True,
        resume_from="some-migration-id",
    )
    assert orch._resolve_truncate(is_first_chunk=True) is False


# ---------------------------------------------------------------------------
# is_first_chunk
# ---------------------------------------------------------------------------


def test_is_first_chunk_passed_correctly(
    mocker: Any,
    make_orchestrator: Any,
) -> None:
    """is_first_chunk=True for chunk 0, False for chunks 1, 2."""
    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=_FAKE_CHUNKS,
    )
    adapter = _MockOrchAdapter()
    orch = make_orchestrator(
        src_adapter=adapter,
        dst_adapter=adapter,
    )
    orch.run()

    assert len(adapter.import_calls) == 3
    # First chunk: is_first_chunk=True
    assert adapter.import_calls[0] == (["test_table"], True)
    # Subsequent chunks: is_first_chunk=False
    assert adapter.import_calls[1] == (["test_table"], False)
    assert adapter.import_calls[2] == (["test_table"], False)


def test_is_first_chunk_multi_table(
    mocker: Any,
    make_orchestrator: Any,
) -> None:
    """Each table's first chunk has is_first_chunk=True."""
    conditions = [
        MigrationCondition(
            table_name="t1", mode="where", chunk_key="id", chunk_size=100,
        ),
        MigrationCondition(
            table_name="t2", mode="where", chunk_key="id", chunk_size=100,
        ),
    ]
    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=_FAKE_CHUNKS,
    )
    adapter = _MockOrchAdapter()
    orch = make_orchestrator(
        conditions=conditions,
        src_adapter=adapter,
        dst_adapter=adapter,
    )
    orch.run()

    # t1 chunk 0 → is_first=True
    assert adapter.import_calls[0] == (["t1"], True)
    # t1 chunk 1 → is_first=False
    assert adapter.import_calls[1] == (["t1"], False)
    # t1 chunk 2 → is_first=False
    assert adapter.import_calls[2] == (["t1"], False)
    # t2 chunk 0 → is_first=True (new table)
    assert adapter.import_calls[3] == (["t2"], True)
    # t2 chunk 1 → is_first=False
    assert adapter.import_calls[4] == (["t2"], False)
    # t2 chunk 2 → is_first=False
    assert adapter.import_calls[5] == (["t2"], False)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_conditions(
    mocker: Any,
    make_orchestrator: Any,
) -> None:
    """Empty conditions list returns success=False."""
    adapter = _MockOrchAdapter()
    orch = make_orchestrator(
        conditions=[],
        src_adapter=adapter,
        dst_adapter=adapter,
    )
    result = orch.run()
    assert result["success"] is False
    assert result["migrated_tables"] == []
    assert result["error_tables"] == []
    assert result["total_rows"] == 0


def test_disabled_condition_skipped(
    mocker: Any,
    make_orchestrator: Any,
) -> None:
    """A disabled migration condition is skipped entirely."""
    conditions = [
        MigrationCondition(
            table_name="enabled_table",
            mode="where",
            chunk_key="id",
            chunk_size=100,
            enabled=True,
        ),
        MigrationCondition(
            table_name="disabled_table",
            mode="where",
            chunk_key="id",
            chunk_size=100,
            enabled=False,
        ),
    ]
    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=_FAKE_CHUNKS,
    )
    adapter = _MockOrchAdapter()
    orch = make_orchestrator(
        conditions=conditions,
        src_adapter=adapter,
        dst_adapter=adapter,
    )
    result = orch.run()
    assert result["success"] is True
    assert len(result["migrated_tables"]) == 1
    assert result["migrated_tables"][0]["name"] == "enabled_table"


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def test_resume_skips_completed_chunks(
    mocker: Any,
    make_orchestrator: Any,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Resume mode skips chunks already recorded in the checkpoint."""
    mocker.patch(
        "core.migration.orchestrator.compute_chunks",
        return_value=_FAKE_CHUNKS,
    )

    from core.migration.resume_manager import ResumeManager

    resume_dir = str(tmp_path / ".db_migrator_resume")
    resume_mgr = ResumeManager(resume_dir=resume_dir)

    # Pre-save checkpoint with chunk 0 completed
    conditions = [
        MigrationCondition(
            table_name="test_table",
            mode="where",
            chunk_key="id",
            chunk_size=100,
        ),
    ]
    meta = MigrationMeta(
        migration_id="resume-test",
        tables=conditions,
        completed_chunks={"test_table": {0}},
    )
    resume_mgr.save(meta)

    # Patch ResumeManager in orchestrator to use our temp dir
    mocker.patch(
        "core.migration.orchestrator.ResumeManager",
        return_value=resume_mgr,
    )

    adapter = _MockOrchAdapter()
    orch = make_orchestrator(
        src_adapter=adapter,
        dst_adapter=adapter,
        resume_from="resume-test",
    )
    result = orch.run()

    assert result["success"] is True
    assert result["total_rows"] == 2  # only chunks 1, 2
    assert len(adapter.export_calls) == 2  # chunks 1, 2
    assert len(adapter.import_calls) == 2  # chunks 1, 2
