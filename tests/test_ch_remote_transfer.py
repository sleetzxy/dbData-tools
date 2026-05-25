"""Tests for ClickHouse remote_transfer and streaming stream_read."""

from __future__ import annotations

import io

import pytest


@pytest.fixture
def src_config() -> dict[str, str | int]:
    return {
        "host": "src.example.com",
        "port": 8123,
        "user": "src_user",
        "password": "src_pass",
        "database": "src_db",
    }


@pytest.fixture
def dst_config() -> dict[str, str | int]:
    return {
        "host": "dst.example.com",
        "port": 8123,
        "user": "dst_user",
        "password": "dst_pass",
        "database": "dst_db",
    }


def test_build_remote_insert_sql_pull(
    src_config: dict[str, str | int],
) -> None:
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    select_sql = "SELECT id, name FROM `src_db`.`events` WHERE dt >= '2024-01-01'"
    sql = adapter.build_remote_insert_sql(
        src_config=src_config,
        dst_table="events",
        select_sql=select_sql,
        schema="dst_db",
        pull=True,
    )

    assert sql.startswith("INSERT INTO `dst_db`.`events` SELECT")
    assert (
        "remote('src.example.com:8123', 'src_db', 'events', "
        "'src_user', 'src_pass')"
    ) in sql
    assert "WHERE dt >= '2024-01-01'" in sql
    assert "SETTINGS max_execution_time=0" in sql
    assert "connect_timeout_with_failover_ms=3000" in sql


def test_build_remote_insert_sql_push(
    src_config: dict[str, str | int],
    dst_config: dict[str, str | int],
) -> None:
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    select_sql = "SELECT id, name FROM events WHERE dt >= '2024-01-01'"
    sql = adapter.build_remote_insert_sql(
        src_config=src_config,
        dst_table="events",
        select_sql=select_sql,
        schema="dst_db",
        pull=False,
        dst_config=dst_config,
    )

    assert sql.startswith("INSERT INTO FUNCTION remote(")
    assert "dst.example.com:8123" in sql
    assert "dst_db.events" in sql
    assert "'dst_user'" in sql
    assert "'dst_pass'" in sql
    assert "SELECT id, name FROM events WHERE dt >= '2024-01-01'" in sql
    assert "SETTINGS max_execution_time=0" in sql


def test_build_remote_insert_sql_with_partition(
    src_config: dict[str, str | int],
) -> None:
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    select_sql = "SELECT * FROM events WHERE id > 0"
    sql = adapter.build_remote_insert_sql(
        src_config=src_config,
        dst_table="events",
        select_sql=select_sql,
        schema="dst_db",
        pull=True,
        partition="202406",
    )

    assert "PARTITION '202406'" in sql
    assert "remote('src.example.com:8123', 'src_db', 'events'" in sql


def test_stream_read_yields_batches_without_loading_all(mocker) -> None:
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    csv_data = "id,val\n1,x\n2,y\n3,z\n"
    mock_stream = io.BytesIO(csv_data.encode("utf-8"))
    mock_client = mocker.MagicMock()
    mock_client.raw_stream.return_value = mock_stream

    columns, batch_iter = adapter.stream_read(
        mock_client, "SELECT id, val FROM t", batch_size=2,
    )

    assert columns == ["id", "val"]
    batches = list(batch_iter)
    assert len(batches) == 2
    assert batches[0] == [("1", "x"), ("2", "y")]
    assert batches[1] == [("3", "z")]
    mock_client.raw_stream.assert_called_once()
    assert "FORMAT CSVWithNames" in mock_client.raw_stream.call_args[0][0]
    mock_client.query.assert_not_called()


def test_stream_read_raises_without_raw_stream(mocker) -> None:
    from db.adapters.clickhouse_adapter import ClickHouseAdapter
    from db.exceptions import ClientCapabilityError

    adapter = ClickHouseAdapter()
    mock_client = mocker.MagicMock(spec=[])

    with pytest.raises(ClientCapabilityError, match="raw_stream"):
        adapter.stream_read(mock_client, "SELECT 1")


def test_remote_transfer_calls_command_with_expected_sql(
    mocker,
    src_config: dict[str, str | int],
) -> None:
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    mock_dst_client = mocker.MagicMock()
    mock_dst_client.host = "dst.example.com"
    mock_dst_client.port = 8123
    mock_dst_client.username = "dst_user"
    mock_dst_client.password = "dst_pass"
    mock_dst_client.database = "dst_db"
    mock_dst_client.command.return_value = mocker.MagicMock(written_rows=42)

    select_sql = "SELECT id FROM events WHERE dt >= '2024-06-01'"
    total = adapter.remote_transfer(
        dst_client=mock_dst_client,
        src_config=src_config,
        dst_table="events",
        select_sql=select_sql,
        schema="dst_db",
        pull=True,
    )

    mock_dst_client.command.assert_called_once()
    executed_sql = mock_dst_client.command.call_args[0][0]
    assert executed_sql.startswith("INSERT INTO `dst_db`.`events`")
    assert "remote('src.example.com:8123', 'src_db', 'events'" in executed_sql
    assert "WHERE dt >= '2024-06-01'" in executed_sql
    assert "SETTINGS max_execution_time=0" in executed_sql
    assert total == 42


def test_remote_transfer_per_physical_partition(
    mocker,
    src_config: dict[str, str | int],
) -> None:
    from db.adapters.clickhouse_adapter import ClickHouseAdapter

    adapter = ClickHouseAdapter()
    mock_dst_client = mocker.MagicMock()
    mock_dst_client.host = "dst.example.com"
    mock_dst_client.port = 8123
    mock_dst_client.username = "dst_user"
    mock_dst_client.password = "dst_pass"
    mock_dst_client.database = "dst_db"
    mock_dst_client.command.side_effect = [
        mocker.MagicMock(written_rows=10),
        mocker.MagicMock(written_rows=20),
    ]

    total = adapter.remote_transfer(
        dst_client=mock_dst_client,
        src_config=src_config,
        dst_table="events",
        select_sql="SELECT * FROM events",
        schema="dst_db",
        pull=True,
        physical_partitions=["202406", "202407"],
    )

    assert mock_dst_client.command.call_count == 2
    first_sql = mock_dst_client.command.call_args_list[0][0][0]
    second_sql = mock_dst_client.command.call_args_list[1][0][0]
    assert "PARTITION '202406'" in first_sql
    assert "PARTITION '202407'" in second_sql
    assert total == 30
