from typing import Any

import pytest

from db.connection import normalize_connection_config


def test_legacy_config_without_db_type_defaults_to_postgresql() -> None:
    legacy = {
        "name": "legacy",
        "host": "127.0.0.1",
        "database": "postgres",
        "user": "postgres",
        "password": "",
    }

    normalized = normalize_connection_config(legacy)

    assert normalized["db_type"] == "postgresql"


def test_postgresql_default_port_and_schema_are_normalized() -> None:
    config = {
        "name": "pg",
        "db_type": "postgresql",
        "host": "127.0.0.1",
        "database": "postgres",
        "user": "postgres",
        "password": "",
        "port": "",
        "schema": "",
    }

    normalized = normalize_connection_config(config)

    assert normalized["port"] == 5432


def test_postgresql_public_schema_normalized() -> None:
    """port 与原用例分列，便于单断言（schema 仍为 public）。"""
    config = {
        "name": "pg",
        "db_type": "postgresql",
        "host": "127.0.0.1",
        "database": "postgres",
        "user": "postgres",
        "password": "",
        "port": "",
        "schema": "",
    }
    normalized = normalize_connection_config(config)
    assert normalized["schema"] == "public"


def test_clickhouse_default_port_and_schema_is_ignored() -> None:
    config = {
        "name": "ch",
        "db_type": "clickhouse",
        "host": "127.0.0.1",
        "database": "default",
        "user": "default",
        "password": "",
        "port": "",
        "schema": "public",
    }

    normalized = normalize_connection_config(config)

    assert normalized["port"] == 8123


def test_clickhouse_schema_cleared() -> None:
    """ClickHouse schema 清空独立断言。"""
    config = {
        "name": "ch",
        "db_type": "clickhouse",
        "host": "127.0.0.1",
        "database": "default",
        "user": "default",
        "password": "",
        "port": "",
        "schema": "public",
    }
    normalized = normalize_connection_config(config)
    assert normalized["schema"] == ""


def test_unsupported_db_type_fails_explicitly() -> None:
    cfg: dict[str, Any] = {"db_type": "mysql"}
    with pytest.raises(ValueError, match="Unsupported db_type"):
        normalize_connection_config(cfg)


def test_db_type_mixed_case_postgresql_normalized() -> None:
    mixed_case = normalize_connection_config({"db_type": " PostgreSQL "})
    assert mixed_case["db_type"] == "postgresql"


def test_db_type_whitespace_maps_to_empty_as_postgresql() -> None:
    empty_value = normalize_connection_config({"db_type": "  "})
    assert empty_value["db_type"] == "postgresql"


def test_db_type_clickhouse_trimmed_lowercase() -> None:
    mixed_clickhouse = normalize_connection_config({"db_type": "  ClickHouse  "})
    assert mixed_clickhouse["db_type"] == "clickhouse"
