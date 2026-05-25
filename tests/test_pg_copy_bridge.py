"""Tests for PostgreSQL adapter CopyBridge integration."""

from __future__ import annotations


def test_copy_stream_transfer_delegates_to_copy_via_bridge(mocker) -> None:
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    mock_src_cursor = mocker.MagicMock()
    mock_dst_cursor = mocker.MagicMock()
    mock_src_client = mocker.MagicMock()
    mock_dst_client = mocker.MagicMock()
    mock_src_client.cursor.return_value.__enter__.return_value = mock_src_cursor
    mock_dst_client.cursor.return_value.__enter__.return_value = mock_dst_cursor

    mock_copy_via_bridge = mocker.patch(
        "core.migration.copy_bridge.copy_via_bridge",
        return_value=42,
    )

    count = adapter.copy_stream_transfer(
        mock_src_client,
        mock_dst_client,
        "SELECT * FROM users WHERE id >= 1 AND id < 100",
        "users",
        ["id", "name"],
        "public",
    )

    assert count == 42
    mock_copy_via_bridge.assert_called_once()
    args = mock_copy_via_bridge.call_args[0]
    assert args[0] is mock_src_cursor
    assert args[1] is mock_dst_cursor
    assert "COPY (SELECT * FROM users" in args[2]
    assert "FORMAT CSV, HEADER false" in args[2]
    assert 'COPY "public"."users"' in args[3] or "COPY public.users" in args[3]
    assert "FROM STDIN WITH (FORMAT CSV)" in args[3]
    assert args[4] == 134_217_728
    mock_dst_client.commit.assert_called_once()


def test_copy_stream_transfer_respects_custom_max_buffer_bytes(mocker) -> None:
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    mock_src_client = mocker.MagicMock()
    mock_dst_client = mocker.MagicMock()
    mock_src_client.cursor.return_value.__enter__.return_value = mocker.MagicMock()
    mock_dst_client.cursor.return_value.__enter__.return_value = mocker.MagicMock()

    mock_copy_via_bridge = mocker.patch(
        "core.migration.copy_bridge.copy_via_bridge",
        return_value=1,
    )

    adapter.copy_stream_transfer(
        mock_src_client,
        mock_dst_client,
        "SELECT 1",
        "t",
        ["id"],
        max_buffer_bytes=8192,
    )

    assert mock_copy_via_bridge.call_args[0][4] == 8192


def test_copy_stream_transfer_uses_bridge_not_stringio_getvalue(mocker) -> None:
    """copy_stream_transfer must pipe through CopyBridge, not StringIO.getvalue()."""
    import io

    from core.migration.copy_bridge import CopyBridge
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    bridge_seen: list[CopyBridge] = []

    def copy_out(_sql: str, buf: CopyBridge) -> None:
        assert not isinstance(buf, io.StringIO)
        bridge_seen.append(buf)
        buf.write(b"1,a\n2,b\n3,c\n")
        buf.close_writer()

    def copy_in(_sql: str, buf: CopyBridge) -> None:
        assert buf is bridge_seen[0]
        assert not isinstance(buf, io.StringIO)
        while buf.read(4096):
            pass

    mock_src_cursor = mocker.MagicMock()
    mock_dst_cursor = mocker.MagicMock()
    mock_src_cursor.copy_expert.side_effect = copy_out
    mock_dst_cursor.copy_expert.side_effect = copy_in
    mock_src_client = mocker.MagicMock()
    mock_dst_client = mocker.MagicMock()
    mock_src_client.cursor.return_value.__enter__.return_value = mock_src_cursor
    mock_dst_client.cursor.return_value.__enter__.return_value = mock_dst_cursor

    count = adapter.copy_stream_transfer(
        mock_src_client,
        mock_dst_client,
        "SELECT * FROM users",
        "users",
        ["id", "name"],
        "public",
    )

    assert count == 3
    assert len(bridge_seen) == 1
    assert isinstance(bridge_seen[0], CopyBridge)
    mock_src_cursor.copy_expert.assert_called_once()
    mock_dst_cursor.copy_expert.assert_called_once()


def test_copy_stream_transfer_empty_returns_zero(mocker) -> None:
    from core.migration.copy_bridge import CopyBridge
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()

    def copy_out(_sql: str, buf: CopyBridge) -> None:
        buf.close_writer()

    def copy_in(_sql: str, buf: CopyBridge) -> None:
        while buf.read(4096):
            pass

    mock_src_cursor = mocker.MagicMock()
    mock_dst_cursor = mocker.MagicMock()
    mock_src_cursor.copy_expert.side_effect = copy_out
    mock_dst_cursor.copy_expert.side_effect = copy_in
    mock_src_client = mocker.MagicMock()
    mock_dst_client = mocker.MagicMock()
    mock_src_client.cursor.return_value.__enter__.return_value = mock_src_cursor
    mock_dst_client.cursor.return_value.__enter__.return_value = mock_dst_cursor

    count = adapter.copy_stream_transfer(
        mock_src_client,
        mock_dst_client,
        "SELECT * FROM users WHERE false",
        "users",
        ["id", "name"],
        "public",
    )

    assert count == 0
