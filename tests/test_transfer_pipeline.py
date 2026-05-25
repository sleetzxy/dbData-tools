"""Tests for TransferPipeline unified routing."""

from __future__ import annotations

import pytest

from core.migration.memory_budget import MemoryBudget
from core.migration.models import (
    ChunkSpec,
    MemoryBudgetConfig,
    MigrationCondition,
    TransferMode,
)
from core.migration.transfer_pipeline import TransferPipeline


@pytest.fixture
def chunk() -> ChunkSpec:
    return ChunkSpec(
        chunk_index=0,
        where_sql="dt >= '2024-01-01'",
        key_start=1,
        key_end=100,
    )


@pytest.fixture
def cond() -> MigrationCondition:
    return MigrationCondition(
        table_name="events",
        mode="where",
        where_clause="status = 1",
        chunk_key="id",
    )


def test_pg_pg_stream_calls_copy_stream_transfer(mocker, cond, chunk) -> None:
    mock_src = mocker.MagicMock()
    mock_src.db_type = "postgresql"
    mock_dst = mocker.MagicMock()
    mock_dst.db_type = "postgresql"

    src_client = mocker.MagicMock()
    dst_client = mocker.MagicMock()

    mock_query = mocker.MagicMock()
    mock_query.as_string.return_value = (
        "SELECT * FROM public.events WHERE (status = 1) AND (dt >= '2024-01-01')"
    )
    mock_src._build_chunked_query.return_value = mock_query
    mock_dst.get_table_columns.return_value = ["id", "status"]
    mock_src.copy_stream_transfer.return_value = 42

    budget = MemoryBudget(MemoryBudgetConfig(limit_mb=512))
    pipeline = TransferPipeline(
        src_adapter=mock_src,
        dst_adapter=mock_dst,
        src_config={"db_type": "postgresql"},
        dst_config={"db_type": "postgresql"},
        src_schema="public",
        dst_schema="public",
        transfer_mode=TransferMode.STREAM,
        memory_budget=budget,
    )

    rows = pipeline.transfer_chunk(
        src_client, dst_client, cond, chunk, "events_target",
    )

    assert rows == 42
    mock_src.copy_stream_transfer.assert_called_once()
    call_kwargs = mock_src.copy_stream_transfer.call_args.kwargs
    assert call_kwargs["max_buffer_bytes"] == budget.buffer_bytes
    mock_src.stream_read.assert_not_called()
    mock_dst.stream_write.assert_not_called()


def test_ck_ck_stream_calls_remote_transfer(mocker, cond, chunk) -> None:
    mock_src = mocker.MagicMock()
    mock_src.db_type = "clickhouse"
    mock_dst = mocker.MagicMock()
    mock_dst.db_type = "clickhouse"

    src_client = mocker.MagicMock()
    dst_client = mocker.MagicMock()

    mock_src._build_chunked_query.return_value = (
        "SELECT * FROM `db`.`events` WHERE (status = 1) AND (dt >= '2024-01-01')"
    )
    mock_src.remote_transfer.return_value = 100

    physical_chunk = ChunkSpec(
        chunk_index=0,
        physical_targets=["part_202401", "part_202402"],
    )

    pipeline = TransferPipeline(
        src_adapter=mock_src,
        dst_adapter=mock_dst,
        src_config={"db_type": "clickhouse", "database": "src_db"},
        dst_config={"db_type": "clickhouse", "database": "dst_db"},
        src_schema="src_db",
        dst_schema="dst_db",
        transfer_mode=TransferMode.STREAM,
    )

    rows = pipeline.transfer_chunk(
        src_client, dst_client, cond, physical_chunk, "events",
    )

    assert rows == 100
    mock_src.remote_transfer.assert_called_once()
    call_kwargs = mock_src.remote_transfer.call_args.kwargs
    assert call_kwargs["pull"] is True
    assert call_kwargs["physical_partitions"] == ["part_202401", "part_202402"]
    mock_src.copy_stream_transfer.assert_not_called()


def test_pg_ck_stream_calls_stream_read_and_write(mocker, cond, chunk) -> None:
    mock_src = mocker.MagicMock()
    mock_src.db_type = "postgresql"
    mock_dst = mocker.MagicMock()
    mock_dst.db_type = "clickhouse"

    src_client = mocker.MagicMock()
    dst_client = mocker.MagicMock()

    mock_query = mocker.MagicMock()
    mock_query.as_string.return_value = "SELECT * FROM public.events"
    mock_src._build_chunked_query.return_value = mock_query
    mock_src.stream_read.return_value = (["id", "status"], iter([[(1, 1)]]))
    mock_dst.stream_write.return_value = 1

    budget = MemoryBudget(MemoryBudgetConfig(limit_mb=256))
    pipeline = TransferPipeline(
        src_adapter=mock_src,
        dst_adapter=mock_dst,
        src_config={"db_type": "postgresql"},
        dst_config={"db_type": "clickhouse"},
        src_schema="public",
        dst_schema="dst_db",
        transfer_mode=TransferMode.STREAM,
        memory_budget=budget,
    )

    rows = pipeline.transfer_chunk(
        src_client, dst_client, cond, chunk, "events",
    )

    assert rows == 1
    mock_src.stream_read.assert_called_once()
    mock_dst.stream_write.assert_called_once()
    expected_batch = budget.compute_batch_rows(1000)
    assert mock_src.stream_read.call_args[0][2] == expected_batch
    mock_src.copy_stream_transfer.assert_not_called()
    mock_src.remote_transfer.assert_not_called()


def test_csv_mode_calls_export_and_import(mocker, cond, chunk, tmp_path) -> None:
    mock_src = mocker.MagicMock()
    mock_src.db_type = "postgresql"
    mock_dst = mocker.MagicMock()
    mock_dst.db_type = "postgresql"

    src_client = mocker.MagicMock()
    dst_client = mocker.MagicMock()

    def _export_csv(**kwargs: object) -> dict[str, object]:
        export_dir = kwargs["export_dir"]
        csv_path = f"{export_dir}/{cond.table_name}.csv"
        with open(csv_path, "w", encoding="utf-8") as handle:
            handle.write("id\n1\n")
        return {"success": True, "total_rows": 1}

    mock_src.export_csv.side_effect = _export_csv
    mock_dst.import_csv.return_value = {"success": True}

    pipeline = TransferPipeline(
        src_adapter=mock_src,
        dst_adapter=mock_dst,
        src_config={"db_type": "postgresql"},
        dst_config={"db_type": "postgresql"},
        src_schema="public",
        dst_schema="public",
        transfer_mode=TransferMode.CSV,
    )

    rows = pipeline.transfer_chunk(
        src_client,
        dst_client,
        cond,
        chunk,
        "events",
        truncate=True,
        temp_dir=str(tmp_path),
    )

    assert rows == 1
    mock_src.export_csv.assert_called_once()
    export_kwargs = mock_src.export_csv.call_args.kwargs
    assert "(status = 1)" in export_kwargs["where_clause"]
    assert "(dt >= '2024-01-01')" in export_kwargs["where_clause"]

    mock_dst.import_csv.assert_called_once()
    import_kwargs = mock_dst.import_csv.call_args.kwargs
    assert import_kwargs["truncate_before"] is True
    mock_src.copy_stream_transfer.assert_not_called()
