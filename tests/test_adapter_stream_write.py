"""Tests for adapter stream_write method."""

from __future__ import annotations


def test_pg_stream_write(mocker):
    mocker.patch("psycopg2.extras.execute_values")
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    mock_cursor = mocker.MagicMock()
    mock_client = mocker.MagicMock()
    mock_client.cursor.return_value.__enter__.return_value = mock_cursor

    rows_batch1 = [(1, "a"), (2, "b")]
    rows_batch2 = [(3, "c")]

    def batch_iter():
        yield rows_batch1
        yield rows_batch2

    count = adapter.stream_write(
        mock_client, "users", ["id", "name"], batch_iter(), "public",
    )
    assert count == 3
    mock_client.commit.assert_called_once()


def test_ch_stream_write(mocker):
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    mock_client = mocker.MagicMock()
    mock_client.database = "mydb"

    def batch_iter():
        yield [(1, "x"), (2, "y")]
        yield [(3, "z")]

    count = adapter.stream_write(
        mock_client, "users", ["id", "val"], batch_iter(), "mydb",
    )
    assert count == 3
    assert mock_client.command.call_count == 2


def test_pg_stream_write_empty(mocker):
    mocker.patch("psycopg2.extras.execute_values")
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    mock_cursor = mocker.MagicMock()
    mock_client = mocker.MagicMock()
    mock_client.cursor.return_value.__enter__.return_value = mock_cursor

    count = adapter.stream_write(
        mock_client, "users", ["id", "name"], iter([]), "public",
    )
    assert count == 0


def test_ch_stream_write_empty(mocker):
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    mock_client = mocker.MagicMock()
    mock_client.database = "mydb"

    count = adapter.stream_write(
        mock_client, "users", ["id", "val"], iter([]), "mydb",
    )
    assert count == 0
    mock_client.command.assert_not_called()
