from typing import Any, Dict, List

from db.connection import close_connection, create_connection, get_db_type
from utils.logger_factory import get_logger

LOGGER_NAME = "exporter"
logger = get_logger(LOGGER_NAME)


def export_tables_to_csv(
    db_config: Dict[str, Any],
    tables: List[str],
    export_dir: str,
    schema: str = "public",
    include_header: bool = True,
) -> Dict[str, Any]:
    """
    使用适配器导出指定表为 CSV 文件

    参数:
        db_config: 数据库连接配置
        tables: 要导出的表名列表
        export_dir: 导出目录
        schema: 数据库模式名（默认为'public'）
        include_header: 是否包含表头

    返回:
        包含导出结果信息的字典
    """
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
                "exported_tables": [],
                "error_tables": [],
                "total_rows": 0,
                "schema": effective_schema,
                "error": "数据库连接失败",
            }

        effective_schema = schema
        if conn.db_type == "clickhouse":
            effective_schema = ""

        try:
            return conn.adapter.export_csv(
                client=conn.client,
                db_config=db_config,
                tables=tables,
                export_dir=export_dir,
                schema=effective_schema,
                include_header=include_header,
                logger=logger,
            )
        except Exception as exc:
            error_msg = f"导出过程中发生错误: {str(exc)}"
            logger.error(error_msg)
            return {
                "success": False,
                "exported_tables": [],
                "error_tables": [],
                "total_rows": 0,
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
            "exported_tables": [],
            "error_tables": [],
            "total_rows": 0,
            "schema": effective_schema,
            "error": error_msg,
        }
    finally:
        if "conn" in locals():
            close_connection(conn, logger)
