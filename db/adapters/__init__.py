from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable

from db.connection import get_db_type


@runtime_checkable
class DatabaseAdapter(Protocol):
    db_type: str

    def create_client(self, db_config: Dict[str, Any]) -> Any:
        ...

    def close_client(self, client: Any) -> None:
        ...

    def export_csv(self, *args: Any, **kwargs: Any) -> None:
        ...

    def import_csv(self, *args: Any, **kwargs: Any) -> None:
        ...

    def export_sql(self, *args: Any, **kwargs: Any) -> None:
        ...


def _build_registry() -> Dict[str, DatabaseAdapter]:
    from db.adapters.clickhouse_adapter import ClickHouseAdapter
    from db.adapters.postgresql_adapter import PostgreSQLAdapter

    return {
        "postgresql": PostgreSQLAdapter(),
        "clickhouse": ClickHouseAdapter(),
    }


def get_adapter_for_db_type(db_type: str) -> DatabaseAdapter:
    registry = _build_registry()
    if db_type not in registry:
        raise ValueError(f"Unsupported db_type: {db_type}")
    return registry[db_type]


def get_adapter_for_config(db_config: Dict[str, Any]) -> DatabaseAdapter:
    db_type = get_db_type(db_config)
    return get_adapter_for_db_type(db_type)
