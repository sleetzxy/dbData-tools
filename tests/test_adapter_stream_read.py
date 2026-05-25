"""Tests for adapter stream_read method."""

from __future__ import annotations


def test_pg_stream_read_yields_batches(mocker) -> None:
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    adapter = PostgreSQLAdapter()
    rows = [(1, "a"), (2, "b"), (3, "c")]
    mock_cursor = mocker.MagicMock()
    # cursor.description returns column metadata tuples; desc[0] is column name
    mock_cursor.description = [
        ("id",),
        ("name",),
    ]
    mock_cursor.fetchmany.side_effect = [rows[:2], rows[2:], []]
    mock_client = mocker.MagicMock()
    mock_client.cursor.return_value = mock_cursor

    columns, batch_iter = adapter.stream_read(
        mock_client, "SELECT * FROM t", batch_size=2,
    )
    assert columns == ["id", "name"]
    batches = list(batch_iter)
    assert len(batches) == 2
    assert batches[0] == [(1, "a"), (2, "b")]
    assert batches[1] == [(3, "c")]


def test_ch_stream_read(mocker) -> None:
    import io

    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    csv_data = "id,val\n1,x\n2,y\n"
    mock_stream = io.BytesIO(csv_data.encode("utf-8"))
    mock_client = mocker.MagicMock()
    mock_client.raw_stream.return_value = mock_stream

    columns, batch_iter = adapter.stream_read(
        mock_client, "SELECT * FROM t", batch_size=10000,
    )
    assert columns == ["id", "val"]
    batches = list(batch_iter)
    assert len(batches) == 1
    assert batches[0] == [("1", "x"), ("2", "y")]
    mock_client.query.assert_not_called()
