import pytest

from db.connection import normalize_connection_config


def test_legacy_config_without_db_type_defaults_to_postgresql():
    legacy = {
        "name": "legacy",
        "host": "127.0.0.1",
        "database": "postgres",
        "user": "postgres",
        "password": "",
    }

    normalized = normalize_connection_config(legacy)

    assert normalized["db_type"] == "postgresql"


def test_postgresql_default_port_and_schema_are_normalized():
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
    assert normalized["schema"] == "public"


def test_clickhouse_default_port_and_schema_is_ignored():
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
    assert normalized["schema"] == ""


def test_unsupported_db_type_fails_explicitly():
    with pytest.raises(ValueError, match="Unsupported db_type"):
        normalize_connection_config({"db_type": "mysql"})


def test_db_type_mixed_case_whitespace_and_empty_are_normalized():
    mixed_case = normalize_connection_config({"db_type": " PostgreSQL "})
    empty_value = normalize_connection_config({"db_type": "  "})
    mixed_clickhouse = normalize_connection_config({"db_type": "  ClickHouse  "})

    assert mixed_case["db_type"] == "postgresql"
    assert empty_value["db_type"] == "postgresql"
    assert mixed_clickhouse["db_type"] == "clickhouse"
