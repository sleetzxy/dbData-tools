"""Tests for adapter get_table_columns method."""

from __future__ import annotations


def test_pg_get_table_columns(mocker):
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    mock_cursor = mocker.MagicMock()
    mock_cursor.__iter__.return_value = iter([
        ("id",), ("name",), ("created_at",),
    ])
    mock_client = mocker.MagicMock()
    mock_client.cursor.return_value.__enter__.return_value = mock_cursor

    columns = adapter.get_table_columns(mock_client, "users", "public")
    assert columns == ["id", "name", "created_at"]


def test_ch_get_table_columns(mocker):
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    mock_client = mocker.MagicMock()
    mock_client.query.return_value.result_columns = ["id", "name", "created_at"]

    columns = adapter.get_table_columns(mock_client, "users", "mydb")
    assert columns == ["id", "name", "created_at"]
