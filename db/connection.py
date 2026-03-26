import logging
from typing import Any, Dict, Literal, Optional, cast

logger = logging.getLogger(__name__)

DBType = Literal["postgresql", "clickhouse"]


class ConnectionHandle:
    __slots__ = ("db_type", "adapter", "client")

    def __init__(self, db_type: DBType, adapter: Any, client: Any) -> None:
        object.__setattr__(self, "db_type", db_type)
        object.__setattr__(self, "adapter", adapter)
        object.__setattr__(self, "client", client)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__slots__:
            object.__setattr__(self, name, value)
        else:
            setattr(self.client, name, value)


def get_db_type(db_config: Dict[str, Any]) -> DBType:
    raw_db_type = db_config.get("db_type", "postgresql")
    db_type = str(raw_db_type).strip().lower() or "postgresql"
    if db_type not in ("postgresql", "clickhouse"):
        raise ValueError(f"Unsupported db_type: {raw_db_type}")
    return cast(DBType, db_type)


def get_default_port(db_type: DBType) -> int:
    if db_type == "postgresql":
        return 5432
    if db_type == "clickhouse":
        return 8123
    raise ValueError(f"Unsupported db_type: {db_type}")


def normalize_connection_config(db_config: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(db_config)
    db_type = get_db_type(normalized)
    normalized["db_type"] = db_type

    raw_port = normalized.get("port")
    if raw_port in (None, ""):
        normalized["port"] = get_default_port(db_type)
    else:
        try:
            normalized["port"] = int(raw_port)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid port value: {raw_port}") from exc

    if db_type == "postgresql":
        schema = str(normalized.get("schema", "")).strip()
        normalized["schema"] = schema or "public"
    else:
        normalized["schema"] = ""

    return normalized


def create_connection(
    db_config: Dict[str, Any], logger: logging.Logger
) -> Optional[ConnectionHandle]:
    try:
        normalized_config = normalize_connection_config(db_config)
        from db.adapters import get_adapter_for_config

        adapter = get_adapter_for_config(normalized_config)
        client = adapter.create_client(normalized_config)
        logger.info(
            f"Database connected: {normalized_config['host']}:{normalized_config['port']}/{normalized_config['database']}"
        )
        return ConnectionHandle(
            db_type=normalized_config["db_type"],
            adapter=adapter,
            client=client,
        )
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None


def close_connection(handle: Optional[ConnectionHandle], logger: logging.Logger) -> None:
    if handle:
        try:
            handle.adapter.close_client(handle.client)
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error while closing database connection: {e}")
