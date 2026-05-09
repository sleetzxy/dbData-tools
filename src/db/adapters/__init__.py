"""Adapter protocol and registry for database backends."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from db.connection import get_db_type


@runtime_checkable
class DatabaseAdapter(Protocol):
    """Minimal operations implemented by concrete database adapters."""

    db_type: str

    def create_client(self, db_config: dict[str, Any]) -> Any: ...

    def close_client(self, client: Any) -> None: ...

    def export_csv(self, *args: Any, **kwargs: Any) -> Any: ...

    def import_csv(self, *args: Any, **kwargs: Any) -> Any: ...

    def export_sql(self, *args: Any, **kwargs: Any) -> Any: ...


def _build_registry() -> dict[str, DatabaseAdapter]:
    from db.adapters.clickhouse_adapter import ClickHouseAdapter
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    return {
        "postgresql": PostgreSQLAdapter(),
        "clickhouse": ClickHouseAdapter(),
    }


def get_adapter_for_db_type(db_type: str) -> DatabaseAdapter:
    """Return the adapter singleton for a normalized ``db_type`` string.

    :param db_type: ``postgresql`` or ``clickhouse``.
    :return: Shared adapter instance.
    :raises ValueError: If ``db_type`` is not registered.
    """
    registry = _build_registry()
    if db_type not in registry:
        raise ValueError(f"Unsupported db_type: {db_type}")
    return registry[db_type]


def get_adapter_for_config(db_config: dict[str, Any]) -> DatabaseAdapter:
    """Resolve an adapter using keys present in ``db_config``.

    :param db_config: Connection parameters including ``db_type``.
    :return: Adapter for the resolved backend.
    """
    db_type = get_db_type(db_config)
    return get_adapter_for_db_type(db_type)
