"""Tests for adapter copy_stream_transfer method."""

from __future__ import annotations


def test_copy_stream_transfer(mocker):
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()

    mock_src_cursor = mocker.MagicMock()
    mock_dst_cursor = mocker.MagicMock()
    mock_src_client = mocker.MagicMock()
    mock_dst_client = mocker.MagicMock()
    mock_src_client.cursor.return_value.__enter__.return_value = mock_src_cursor
    mock_dst_client.cursor.return_value.__enter__.return_value = mock_dst_cursor

    # Simulate COPY TO STDOUT writing CSV data
    def copy_to_stdout(sql_str, buf):
        buf.write("1,a\n2,b\n3,c\n")

    mock_src_cursor.copy_expert.side_effect = copy_to_stdout

    count = adapter.copy_stream_transfer(
        mock_src_client, mock_dst_client,
        "SELECT * FROM users WHERE id >= 1 AND id < 100",
        "users", ["id", "name"], "public",
    )
    assert count == 3
    mock_dst_cursor.copy_expert.assert_called_once()


def test_copy_stream_transfer_empty(mocker):
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()

    mock_src_cursor = mocker.MagicMock()
    mock_dst_cursor = mocker.MagicMock()
    mock_src_client = mocker.MagicMock()
    mock_dst_client = mocker.MagicMock()
    mock_src_client.cursor.return_value.__enter__.return_value = mock_src_cursor
    mock_dst_client.cursor.return_value.__enter__.return_value = mock_dst_cursor

    def copy_to_stdout(sql_str, buf):
        buf.close_writer()

    mock_src_cursor.copy_expert.side_effect = copy_to_stdout

    count = adapter.copy_stream_transfer(
        mock_src_client, mock_dst_client,
        "SELECT * FROM users WHERE false",
        "users", ["id", "name"], "public",
    )
    assert count == 0
    mock_dst_cursor.copy_expert.assert_called_once()


def test_copy_stream_transfer_embedded_newlines(mocker):
    """Row count is correct even when CSV fields contain newlines."""
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()

    mock_src_cursor = mocker.MagicMock()
    mock_dst_cursor = mocker.MagicMock()
    mock_src_client = mocker.MagicMock()
    mock_dst_client = mocker.MagicMock()
    mock_src_client.cursor.return_value.__enter__.return_value = mock_src_cursor
    mock_dst_client.cursor.return_value.__enter__.return_value = mock_dst_cursor

    # Two rows: first has a quoted field with embedded newline
    def copy_to_stdout(sql_str, buf):
        buf.write('1,"line1\nline2"\n2,simple\n')

    mock_src_cursor.copy_expert.side_effect = copy_to_stdout

    count = adapter.copy_stream_transfer(
        mock_src_client, mock_dst_client,
        "SELECT * FROM t",
        "users", ["id", "description"], "public",
    )
    assert count == 2
