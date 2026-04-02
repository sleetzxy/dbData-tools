"""
数据迁移核心逻辑

将源库中指定的多张表通过临时 CSV 中转迁移到目标库。
支持 PostgreSQL / ClickHouse 同构及异构迁移。
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def migrate_tables(
    src_config: Dict[str, Any],
    dst_config: Dict[str, Any],
    table_names: List[str],
    truncate_before: bool = True,
    src_adapter: Optional[Any] = None,
    dst_adapter: Optional[Any] = None,
    logger: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    将源库中指定的多张表迁移到目标库。

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
    result: Dict[str, Any] = {
        "success": True,
        "migrated_tables": [],
        "error_tables": [],
        "total_rows": 0,
    }

    table_names = [t.strip() for t in table_names if t.strip()]
    if not table_names:
        result["success"] = False
        result["error"] = "未指定要迁移的表名"
        return result

    # 获取 adapter
    if src_adapter is None or dst_adapter is None:
        from db.adapters import get_adapter_for_config
        if src_adapter is None:
            src_adapter = get_adapter_for_config(src_config)
        if dst_adapter is None:
            dst_adapter = get_adapter_for_config(dst_config)

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
                # 导出
                export_result = src_adapter.export_csv(
                    client=src_client,
                    db_config=src_config,
                    tables=[table],
                    export_dir=table_tmp_dir,
                    schema=src_schema,
                    include_header=True,
                    logger=logger,
                )
                if not export_result.get("success", True) and export_result.get("error_tables"):
                    raise RuntimeError(
                        export_result["error_tables"][0].get("error", "导出失败")
                    )

                exported = export_result.get("exported_tables", [])
                row_count = exported[0].get("rows", 0) if exported else 0

                # 导入
                import_result = dst_adapter.import_csv(
                    client=dst_client,
                    db_config=dst_config,
                    table_names=[table],
                    data_dir=table_tmp_dir,
                    schema=dst_schema,
                    truncate_before=truncate_before,
                    logger=logger,
                )
                if not import_result.get("success", True) and import_result.get("error_tables"):
                    err = import_result["error_tables"][0]
                    raise RuntimeError(err.get("error", "导入失败"))

                result["migrated_tables"].append({"name": table, "rows": row_count})
                result["total_rows"] += row_count

                if logger:
                    logger.info(f"表 {table} 迁移完成，共 {row_count} 行")

            except Exception as exc:
                error_msg = str(exc)
                if logger:
                    logger.error(f"表 {table} 迁移失败: {error_msg}")
                result["error_tables"].append({"name": table, "error": error_msg})
                result["success"] = False
            finally:
                shutil.rmtree(table_tmp_dir, ignore_errors=True)

    except Exception as exc:
        error_msg = f"迁移过程发生错误: {exc}"
        if logger:
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
