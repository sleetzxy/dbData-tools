"""Tests for adapter get_table_columns method."""

from __future__ import annotations

import pytest


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
    mock_client.query.return_value.result_rows = [("id",), ("name",), ("created_at",)]

    columns = adapter.get_table_columns(mock_client, "users", "mydb")
    assert columns == ["id", "name", "created_at"]


def test_pg_get_table_columns_empty_result(mocker):
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    mock_cursor = mocker.MagicMock()
    mock_cursor.__iter__.return_value = iter([])
    mock_client = mocker.MagicMock()
    mock_client.cursor.return_value.__enter__.return_value = mock_cursor

    columns = adapter.get_table_columns(mock_client, "empty_table")
    assert columns == []


def test_pg_get_table_columns_invalid_table_name(mocker):
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    mock_client = mocker.MagicMock()

    with pytest.raises(ValueError, match="Invalid table identifier"):
        adapter.get_table_columns(mock_client, "")


def test_ch_get_table_columns_default_database(mocker):
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    mock_client = mocker.MagicMock()
    mock_client.database = "default_db"
    mock_client.query.return_value.result_rows = [("col1",), ("col2",)]

    columns = adapter.get_table_columns(mock_client, "users", database="")
    assert columns == ["col1", "col2"]
    mock_client.query.assert_called_once()
    _, kwargs = mock_client.query.call_args
    assert kwargs["parameters"]["database"] == "default_db"
