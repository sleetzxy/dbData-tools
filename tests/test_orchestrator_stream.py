"""Tests for MigrationOrchestrator streaming transfer."""

from __future__ import annotations


def test_orchestrator_stream_mode_no_temp_dir(mocker):
    """STREAM mode must not create a migration temp directory."""
    from core.migration.models import MigrationCondition, TransferMode
    from core.migration.orchestrator import MigrationOrchestrator

    mkdtemp = mocker.patch("core.migration.orchestrator.tempfile.mkdtemp")
    mock_src_adapter = mocker.MagicMock()
    mock_src_adapter.db_type = "postgresql"
    mock_src_adapter.create_client.return_value = mocker.MagicMock()
    mock_dst_adapter = mocker.MagicMock()
    mock_dst_adapter.db_type = "postgresql"
    mock_dst_adapter.create_client.return_value = mocker.MagicMock()

    mock_chunk = mocker.MagicMock()
    mock_chunk.chunk_index = 0
    mock_chunk.key_start = 1
    mock_chunk.key_end = 100
    mocker.patch.object(
        MigrationOrchestrator,
        "_compute_chunks",
        return_value=[mock_chunk],
    )

    mock_src_adapter.copy_stream_transfer.return_value = 1
    mock_src_adapter._build_chunked_query.return_value = mocker.MagicMock()
    mock_src_adapter._build_chunked_query.return_value.as_string.return_value = (
        "SELECT * FROM users"
    )

    cond = MigrationCondition(table_name="users", mode="where")
    orch = MigrationOrchestrator(
        src_config={"db_type": "postgresql"},
        dst_config={"db_type": "postgresql"},
        conditions=[cond],
        src_adapter=mock_src_adapter,
        dst_adapter=mock_dst_adapter,
    )
    assert orch.transfer_mode == TransferMode.STREAM

    result = orch.run()
    assert result["success"] is True
    mkdtemp.assert_not_called()


def test_orchestrator_stream_mode_pg_to_pg(mocker):
    from core.migration.models import MigrationCondition, TransferMode
    from core.migration.orchestrator import MigrationOrchestrator

    mock_src_adapter = mocker.MagicMock()
    mock_src_adapter.db_type = "postgresql"
    mock_src_adapter.create_client.return_value = mocker.MagicMock()
    mock_dst_adapter = mocker.MagicMock()
    mock_dst_adapter.db_type = "postgresql"
    mock_dst_adapter.create_client.return_value = mocker.MagicMock()

    mock_chunk = mocker.MagicMock()
    mock_chunk.chunk_index = 0
    mock_chunk.key_start = 1
    mock_chunk.key_end = 100
    mocker.patch.object(
        MigrationOrchestrator,
        "_compute_chunks",
        return_value=[mock_chunk],
    )

    mock_src_adapter.copy_stream_transfer.return_value = 50000
    mock_src_adapter._build_chunked_query.return_value = mocker.MagicMock()
    mock_src_adapter._build_chunked_query.return_value.as_string.return_value = (
        "SELECT * FROM users WHERE id >= 1 AND id < 100"
    )

    cond = MigrationCondition(table_name="users", mode="where")
    orch = MigrationOrchestrator(
        src_config={"db_type": "postgresql"},
        dst_config={"db_type": "postgresql"},
        conditions=[cond],
        src_adapter=mock_src_adapter,
        dst_adapter=mock_dst_adapter,
        transfer_mode=TransferMode.STREAM,
    )

    result = orch.run()
    assert result["success"] is True
    mock_src_adapter.copy_stream_transfer.assert_called_once()


def test_orchestrator_stream_mode_heterogeneous(mocker):
    from core.migration.models import MigrationCondition, TransferMode
    from core.migration.orchestrator import MigrationOrchestrator

    mock_src_adapter = mocker.MagicMock()
    mock_src_adapter.db_type = "postgresql"
    mock_src_adapter.create_client.return_value = mocker.MagicMock()
    mock_dst_adapter = mocker.MagicMock()
    mock_dst_adapter.db_type = "clickhouse"
    mock_dst_adapter.create_client.return_value = mocker.MagicMock()

    mock_chunk = mocker.MagicMock()
    mock_chunk.chunk_index = 0
    mock_chunk.key_start = 1
    mock_chunk.key_end = 100
    mocker.patch.object(
        MigrationOrchestrator,
        "_compute_chunks",
        return_value=[mock_chunk],
    )

    mock_src_adapter._build_chunked_query.return_value = mocker.MagicMock()
    mock_src_adapter._build_chunked_query.return_value.as_string.return_value = (
        "SELECT * FROM users WHERE id >= 1 AND id < 100"
    )
    mock_src_adapter.stream_read.return_value = (
        ["id", "name"],
        iter([[(1, "a"), (2, "b")]]),
    )
    mock_dst_adapter.stream_write.return_value = 2

    cond = MigrationCondition(table_name="users", mode="where")
    orch = MigrationOrchestrator(
        src_config={"db_type": "postgresql"},
        dst_config={"db_type": "clickhouse"},
        conditions=[cond],
        src_adapter=mock_src_adapter,
        dst_adapter=mock_dst_adapter,
        transfer_mode=TransferMode.STREAM,
    )

    result = orch.run()
    assert result["success"] is True
    mock_src_adapter.stream_read.assert_called_once()
    mock_dst_adapter.stream_write.assert_called_once()


def test_orchestrator_target_table_mapping(mocker):
    from core.migration.models import MigrationCondition, TransferMode
    from core.migration.orchestrator import MigrationOrchestrator

    mock_src_adapter = mocker.MagicMock()
    mock_src_adapter.db_type = "postgresql"
    mock_src_adapter.create_client.return_value = mocker.MagicMock()
    mock_dst_adapter = mocker.MagicMock()
    mock_dst_adapter.db_type = "postgresql"
    mock_dst_adapter.create_client.return_value = mocker.MagicMock()

    mock_chunk = mocker.MagicMock()
    mock_chunk.chunk_index = 0
    mock_chunk.key_start = 1
    mock_chunk.key_end = 100
    mocker.patch.object(
        MigrationOrchestrator,
        "_compute_chunks",
        return_value=[mock_chunk],
    )

    mock_src_adapter._build_chunked_query.return_value = mocker.MagicMock()
    mock_src_adapter._build_chunked_query.return_value.as_string.return_value = (
        "SELECT * FROM source_users WHERE id >= 1 AND id < 100"
    )
    mock_src_adapter.copy_stream_transfer.return_value = 100

    cond = MigrationCondition(
        table_name="source_users", target_table="target_users", mode="where",
    )
    orch = MigrationOrchestrator(
        src_config={"db_type": "postgresql"},
        dst_config={"db_type": "postgresql"},
        conditions=[cond],
        src_adapter=mock_src_adapter,
        dst_adapter=mock_dst_adapter,
        transfer_mode=TransferMode.STREAM,
    )

    result = orch.run()
    assert result["success"] is True
    # Verify target table name is used
    call_args = mock_src_adapter.copy_stream_transfer.call_args
    assert call_args[0][3] == "target_users"  # dst_table parameter
