from typing import Any, Dict, List, Optional

from db.connection import close_connection, create_connection, get_db_type
from utils.logger_factory import get_logger

LOGGER_NAME = "exporter_db"
logger = get_logger(LOGGER_NAME)


def export_database_to_sql(
    db_config: Dict[str, Any],
    export_dir: str,
    schema: str = "public",
    exclude_tables: Optional[List[str]] = None,
    include_truncate: bool = True,
) -> Dict[str, Any]:
    """Export database to SQL using adapter dispatch."""
    try:
        conn = create_connection(db_config, logger)
        if not conn:
            effective_schema = schema
            try:
                if get_db_type(db_config) == "clickhouse":
                    effective_schema = ""
            except Exception:
                pass
            return {
                "success": False,
                "schema": effective_schema,
                "error": "数据库连接失败",
            }

        effective_schema = schema
        if conn.db_type == "clickhouse":
            effective_schema = ""

        try:
            return conn.adapter.export_sql(
                client=conn.client,
                db_config=db_config,
                export_dir=export_dir,
                schema=effective_schema,
                exclude_tables=exclude_tables,
                include_truncate=include_truncate,
                logger=logger,
            )
        except Exception as exc:
            error_msg = f"导出过程中发生错误: {str(exc)}"
            logger.error(error_msg)
            return {
                "success": False,
                "schema": effective_schema,
                "error": error_msg,
            }
    except Exception as exc:
        error_msg = f"导出过程中发生错误: {str(exc)}"
        logger.error(error_msg)
        effective_schema = schema
        try:
            if get_db_type(db_config) == "clickhouse":
                effective_schema = ""
        except Exception:
            pass
        return {
            "success": False,
            "schema": effective_schema,
            "error": error_msg,
        }
    finally:
        if "conn" in locals():
            close_connection(conn, logger)
