"""
数据迁移核心逻辑

将源库中指定的多张表通过临时 CSV 中转迁移到目标库。
支持 PostgreSQL / ClickHouse 同构及异构迁移。
支持条件迁移、分块迁移、断点续传。
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any

from core.migration.models import MigrationCondition
from core.migration.orchestrator import MigrationOrchestrator
from utils.logger_factory import get_logger

LOGGER_NAME = "migrate"
logger = get_logger(LOGGER_NAME)


def migrate_tables(
    src_config: dict[str, Any],
    dst_config: dict[str, Any],
    table_names: list[str],
    truncate_before: bool = True,
    src_adapter: Any | None = None,
    dst_adapter: Any | None = None,
    logger: Any | None = None,
) -> dict[str, Any]:
    """
    将源库中指定的多张表迁移到目标库。

    当注入 ``src_adapter`` / ``dst_adapter`` 时（测试模式），使用简化的
    循环迁移路径，不涉及分块策略和断点恢复。

    Args:
        src_config: 源库连接配置（含 db_type）
        dst_config: 目标库连接配置（含 db_type）
        table_names: 要迁移的表名列表
        truncate_before: 迁移前是否清空目标表
        src_adapter: 测试用注入，生产时自动从 db_type 获取
        dst_adapter: 测试用注入，生产时自动从 db_type 获取
        logger: 日志记录器

    Returns:
        {
            "success": bool,
            "migrated_tables": [{"name": str, "rows": int}, ...],
            "error_tables": [{"name": str, "error": str}, ...],
            "total_rows": int,
        }
    """
    _log = logger or logging.getLogger(__name__)

    table_names = [t.strip() for t in table_names if t.strip()]
    if not table_names:
        return {
            "success": False,
            "error": "未指定要迁移的表名",
            "migrated_tables": [],
            "error_tables": [],
            "total_rows": 0,
        }

    # 测试模式（注入 adapter）：保留原有简单迁移路径，不依赖分块策略
    if src_adapter is not None and dst_adapter is not None:
        return _migrate_tables_legacy(
            src_config=src_config,
            dst_config=dst_config,
            table_names=table_names,
            truncate_before=truncate_before,
            src_adapter=src_adapter,
            dst_adapter=dst_adapter,
            logger=_log,
        )

    # 生产模式：委托给 MigrationOrchestrator（分块 + 断点 + 重试）
    conditions = [
        MigrationCondition(table_name=name, mode="where", enabled=True)
        for name in table_names
    ]

    orchestrator = MigrationOrchestrator(
        src_config=src_config,
        dst_config=dst_config,
        conditions=conditions,
        truncate_before=truncate_before,
        logger=_log,
    )

    try:
        return orchestrator.run()
    except Exception as exc:
        error_msg = f"迁移过程发生错误: {exc}"
        _log.error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "migrated_tables": [],
            "error_tables": [],
            "total_rows": 0,
        }


def _migrate_tables_legacy(
    src_config: dict[str, Any],
    dst_config: dict[str, Any],
    table_names: list[str],
    truncate_before: bool,
    src_adapter: Any,
    dst_adapter: Any,
    logger: Any,
) -> dict[str, Any]:
    """简化的单表完整导出/导入路径，供测试及无分块需求场景使用。"""
    result: dict[str, Any] = {
        "success": True,
        "migrated_tables": [],
        "error_tables": [],
        "total_rows": 0,
    }

    tmp_dir = tempfile.mkdtemp(prefix="db_migrator_")
    src_client = None
    dst_client = None

    try:
        src_client = src_adapter.create_client(src_config)
        dst_client = dst_adapter.create_client(dst_config)

        src_schema = src_config.get("schema", "")
        dst_schema = dst_config.get("schema", "")

        for table in table_names:
            table_tmp_dir = os.path.join(tmp_dir, table)
            os.makedirs(table_tmp_dir, exist_ok=True)
            try:
                export_result = src_adapter.export_csv(
                    client=src_client,
                    db_config=src_config,
                    table=table,
                    export_dir=table_tmp_dir,
                    schema=src_schema,
                    include_header=True,
                    logger=logger,
                )
                if not export_result.get("success", True):
                    err = (export_result.get("error_tables") or [{}])[0].get(
                        "error"
                    ) or export_result.get("error", "导出失败")
                    raise RuntimeError(err)

                exported = export_result.get("exported_tables", [])
                row_count = exported[0].get("rows", 0) if exported else 0

                import_result = dst_adapter.import_csv(
                    client=dst_client,
                    db_config=dst_config,
                    table_names=[table],
                    data_dir=table_tmp_dir,
                    schema=dst_schema,
                    truncate_before=truncate_before,
                    is_first_chunk=True,
                    logger=logger,
                )
                if not import_result.get("success", True):
                    err_tables = import_result.get("error_tables") or []
                    err = (
                        err_tables[0].get("error") if err_tables else None
                    ) or import_result.get("error", "导入失败")
                    raise RuntimeError(err)

                result["migrated_tables"].append({"name": table, "rows": row_count})
                result["total_rows"] += row_count

                logger.info(f"表 {table} 迁移完成，共 {row_count} 行")

            except Exception as exc:
                error_msg = str(exc)
                logger.error(f"表 {table} 迁移失败: {error_msg}")
                result["error_tables"].append({"name": table, "error": error_msg})
                result["success"] = False
            finally:
                shutil.rmtree(table_tmp_dir, ignore_errors=True)

    except Exception as exc:
        error_msg = f"迁移过程发生错误: {exc}"
        logger.error(error_msg)
        result["success"] = False
        result["error"] = error_msg
    finally:
        if src_client is not None:
            try:
                src_adapter.close_client(src_client)
            except Exception:
                pass
        if dst_client is not None:
            try:
                dst_adapter.close_client(dst_client)
            except Exception:
                pass
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return result
