"""Connection configuration normalization and adapter-backed client handles."""

from __future__ import annotations

import logging
from typing import Any, Literal, cast

logger = logging.getLogger(__name__)

DBType = Literal["postgresql", "clickhouse"]


class ConnectionHandle:
    """Transparent wrapper that forwards attribute access to the live DB client.

    :ivar db_type: Resolved backend key (``postgresql`` or ``clickhouse``).
    :ivar adapter: Registry :class:`~db.adapters.DatabaseAdapter` instance.
    :ivar client: Underlying driver connection object.
    """

    __slots__ = ("adapter", "client", "db_type")

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


def get_db_type(db_config: dict[str, Any]) -> DBType:
    """Return a normalized database type string from configuration.

    :param db_config: Mapping that may contain ``db_type``.
    :return: ``postgresql`` or ``clickhouse``.
    :raises ValueError: If ``db_type`` is missing or not supported.
    """
    raw_db_type = db_config.get("db_type", "postgresql")
    db_type = str(raw_db_type).strip().lower() or "postgresql"
    if db_type not in ("postgresql", "clickhouse"):
        raise ValueError(f"Unsupported db_type: {raw_db_type}")
    return cast(DBType, db_type)


def get_default_port(db_type: DBType) -> int:
    """Return the conventional TCP port for ``db_type``.

    :param db_type: Backend discriminator.
    :return: Default port number.
    :raises ValueError: If ``db_type`` is unknown.
    """
    if db_type == "postgresql":
        return 5432
    if db_type == "clickhouse":
        return 8123
    raise ValueError(f"Unsupported db_type: {db_type}")


def normalize_connection_config(db_config: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults (port, schema) and coerce types for a connection profile.

    :param db_config: Raw settings from storage or the UI.
    :return: A new dict safe to pass to adapters.
    """
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
    db_config: dict[str, Any], logger: logging.Logger
) -> ConnectionHandle | None:
    """Open a client through the adapter registry, or log and return ``None``.

    Configuration problems (bad port, unknown ``db_type``) and driver failures
    are logged at error level; this keeps GUI call sites simple.

    :param db_config: Connection parameters (see :func:`normalize_connection_config`).
    :param logger: Active logger for the calling workflow.
    :return: A handle, or ``None`` when connection cannot be established.
    """
    try:
        normalized_config = normalize_connection_config(db_config)
        from db.adapters import get_adapter_for_config

        adapter = get_adapter_for_config(normalized_config)
        client = adapter.create_client(normalized_config)
        host = normalized_config["host"]
        port = normalized_config["port"]
        database = normalized_config["database"]
        logger.info("Database connected: %s:%s/%s", host, port, database)
        return ConnectionHandle(
            db_type=normalized_config["db_type"],
            adapter=adapter,
            client=client,
        )
    except (KeyError, TypeError, ValueError, OSError) as exc:
        logger.error("Database connection failed (configuration or I/O): %s", exc)
        return None
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
        return None


def close_connection(
    handle: ConnectionHandle | None, logger: logging.Logger
) -> None:
    """Best-effort shutdown for ``handle`` using the bound adapter.

    :param handle: Live handle from :func:`create_connection`, or ``None``.
    :param logger: Active logger for the calling workflow.
    """
    if handle:
        try:
            handle.adapter.close_client(handle.client)
            logger.info("Database connection closed")
        except OSError as exc:
            logger.error("Error while closing database connection: %s", exc)
        except Exception as exc:
            logger.error("Error while closing database connection: %s", exc)
