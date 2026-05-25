"""编排器：协调分块迁移的完整流程（导出 → 导入 → 断点续传）。"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from typing import Any

from core.migration.chunk_strategy import compute_chunks
from core.migration.memory_budget import MemoryBudget
from core.migration.models import (
    BindType,
    ChunkProgress,
    ChunkSpec,
    MigrationCondition,
    MigrationMeta,
    SplitMode,
    TableMigrationResult,
    TransferMode,
)
from core.migration.resume_manager import ResumeManager
from core.migration.split_strategy import (
    compute_split_chunks,
    compute_split_chunks_with_client,
)
from core.migration.transfer_pipeline import TransferPipeline
from db.adapters import get_adapter_for_config

logger = logging.getLogger("migrate.orchestrator")

_MAX_RETRIES = 3


class MigrationOrchestrator:
    """协调分块迁移的完整流程。

    职责
        - 根据迁移条件逐表执行分块导出与导入
        - 支持断点续传（基于 ResumeManager）
        - 自动检测分块键并生成分块列表
        - 单分块失败不中断整表迁移（记录错误，继续下一分块）
        - 重试机制：导出+导入为一个原子单元，失败后指数退避重试
        - 进度回调与断点持久化

    用法::

        orch = MigrationOrchestrator(src_config, dst_config, conditions)
        result = orch.run()
    """

    def __init__(
        self,
        src_config: dict[str, Any],
        dst_config: dict[str, Any],
        conditions: list[MigrationCondition],
        truncate_before: bool = True,
        resume_from: str | None = None,
        logger: Any | None = None,
        progress_callback: Callable[[ChunkProgress], None] | None = None,
        src_adapter: Any = None,
        dst_adapter: Any = None,
        transfer_mode: TransferMode = TransferMode.STREAM,
        memory_budget: MemoryBudget | None = None,
        stream_batch_size: int = 10000,
    ) -> None:
        self.src_config = src_config
        self.dst_config = dst_config
        self.conditions = conditions
        self.truncate_before = truncate_before
        self.resume_from = resume_from
        self.logger = logger or logging.getLogger("migrate.orchestrator")
        self.progress_callback = progress_callback

        self.src_adapter = src_adapter or get_adapter_for_config(src_config)
        self.dst_adapter = dst_adapter or get_adapter_for_config(dst_config)
        self.resume_mgr = ResumeManager()
        self.transfer_mode = transfer_mode
        self.memory_budget = memory_budget
        self.stream_batch_size = stream_batch_size

        # 解析 schema：PG 默认 "public"，CH 用配置中的 schema 或空串
        self.src_schema = src_config.get("schema", "")
        if not self.src_schema and self.src_adapter.db_type == "postgresql":
            self.src_schema = "public"

        self.dst_schema = dst_config.get("schema", "")
        if not self.dst_schema and self.dst_adapter.db_type == "postgresql":
            self.dst_schema = "public"

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """执行完整的迁移流程。

        :return: 与 ``migrate_tables()`` 兼容的返回字典：

            .. code-block:: python

                {
                    "success": bool,
                    "migrated_tables": list[str],
                    "error_tables": list[dict],
                    "total_rows": int,
                }
        """
        src_client = None
        dst_client = None
        temp_dir: str | None = None
        migration_id = self.resume_from or str(uuid.uuid4())
        meta = MigrationMeta(migration_id=migration_id, tables=self.conditions)
        resume_mode = self.resume_from is not None

        try:
            # 续传模式：加载已有断点
            if resume_mode:
                loaded = self.resume_mgr.load(migration_id)
                if loaded is not None:
                    meta = loaded
                    self.logger.info(
                        "加载迁移断点 %s (已完成 %d 个分块)",
                        migration_id,
                        sum(len(v) for v in meta.completed_chunks.values()),
                    )
                else:
                    self.logger.warning(
                        "未找到迁移断点 %s，将以全新迁移开始", migration_id,
                    )

            src_client = self.src_adapter.create_client(self.src_config)
            dst_client = self.dst_adapter.create_client(self.dst_config)

            if self.transfer_mode == TransferMode.CSV:
                temp_dir = tempfile.mkdtemp(prefix="db_migrate_")

            pipeline = TransferPipeline(
                src_adapter=self.src_adapter,
                dst_adapter=self.dst_adapter,
                src_config=self.src_config,
                dst_config=self.dst_config,
                src_schema=self.src_schema,
                dst_schema=self.dst_schema,
                transfer_mode=self.transfer_mode,
                memory_budget=self.memory_budget,
                logger=self.logger,
            )

            # 预先计算总块数（用于进度回传）
            total_across_all = self._count_total_chunks(src_client)
            completed_across = self._count_completed_chunks(meta)

            results: list[TableMigrationResult] = []
            total_rows = 0

            enabled = [c for c in self.conditions if c.enabled]
            for cond in enabled:
                table_result = self._migrate_table(
                    cond=cond,
                    src_client=src_client,
                    dst_client=dst_client,
                    meta=meta,
                    pipeline=pipeline,
                    temp_dir=temp_dir,
                    total_across_all=total_across_all,
                    completed_across=completed_across,
                    resume_mode=resume_mode,
                )
                results.append(table_result)
                total_rows += table_result.total_rows
                completed_across += table_result.completed_chunks

            # 全部完成 → 清理断点；部分失败 → 保存当前进度
            if all(r.success for r in results):
                self.resume_mgr.delete(migration_id)
                self.logger.info("迁移全部完成，断点已删除")
            else:
                self.resume_mgr.save(meta)
                self.logger.warning("迁移部分完成，断点已保存")

            return self._build_result(results, total_rows)

        except Exception as exc:
            self.logger.error("迁移流程异常: %s", exc, exc_info=True)
            try:
                self.resume_mgr.save(meta)
            except Exception:
                self.logger.warning("保存断点失败", exc_info=True)
            return {
                "success": False,
                "migrated_tables": [],
                "error_tables": [],
                "total_rows": 0,
            }

        finally:
            self._cleanup_temp_dir(temp_dir)
            self._close_client(src_client, self.src_adapter)
            self._close_client(dst_client, self.dst_adapter)

    # ------------------------------------------------------------------
    # 分块迁移
    # ------------------------------------------------------------------

    def _compute_chunks(
        self,
        client: Any,
        cond: MigrationCondition,
    ) -> list[ChunkSpec]:
        """根据 split 配置或 legacy KEY_RANGE 策略生成分块列表。"""
        split = cond.split
        has_range = bool(split.range_start.strip() and split.range_end.strip())

        if split.mode != SplitMode.KEY_RANGE and has_range:
            if (
                split.mode == SplitMode.PHYSICAL_PARTITION
                and split.bind_type == BindType.METADATA_LIST
            ):
                return compute_split_chunks_with_client(
                    split, self.src_adapter, client, self.src_schema,
                )
            return compute_split_chunks(split)

        return compute_chunks(
            self.src_adapter, client, cond.table_name, cond, self.src_schema,
        )

    def _migrate_table(
        self,
        cond: MigrationCondition,
        src_client: Any,
        dst_client: Any,
        meta: MigrationMeta,
        pipeline: TransferPipeline,
        temp_dir: str | None,
        total_across_all: int,
        completed_across: int,
        resume_mode: bool,
    ) -> TableMigrationResult:
        """迁移单张表（分块执行）。"""
        chunks = self._compute_chunks(src_client, cond)
        total_chunks = len(chunks)
        completed_chunks_count = 0
        total_rows = 0
        last_error = ""

        completed_set = meta.completed_chunks.get(cond.table_name, set())
        target_table = cond.target_table or cond.table_name

        for chunk in chunks:
            chunk_index = chunk.chunk_index

            # 续传模式：跳过已完成分块（已计入 caller 的 completed_across）
            if resume_mode and chunk_index in completed_set:
                self.logger.info(
                    "跳过已完成分块: %s[%d]", cond.table_name, chunk_index,
                )
                continue

            do_truncate = self._resolve_truncate(chunk_index == 0)
            if (
                do_truncate
                and self.transfer_mode == TransferMode.STREAM
            ):
                self._truncate_target(dst_client, target_table)

            # 重试循环（传输作为一个原子单元）
            rows_in_chunk = 0
            chunk_ok = False
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    rows_in_chunk = pipeline.transfer_chunk(
                        src_client=src_client,
                        dst_client=dst_client,
                        cond=cond,
                        chunk=chunk,
                        target_table=target_table,
                        truncate=do_truncate,
                        temp_dir=temp_dir,
                    )
                    chunk_ok = True
                    break  # 成功，退出重试循环
                except Exception as exc:
                    if attempt == _MAX_RETRIES:
                        self.logger.error(
                            "分块 %s[%d] 迁移失败（已重试 %d 次）: %s",
                            cond.table_name, chunk_index, _MAX_RETRIES, exc,
                        )
                        last_error = str(exc)
                    else:
                        wait = 2**attempt
                        self.logger.warning(
                            "分块 %s[%d] 失败（第 %d/%d 次），%ds 后重试: %s",
                            cond.table_name, chunk_index,
                            attempt + 1, _MAX_RETRIES, wait, exc,
                        )
                        time.sleep(wait)

            # 重试耗尽，记录错误并继续下一分块
            if not chunk_ok:
                continue

            total_rows += rows_in_chunk

            # 更新断点
            meta.completed_chunks.setdefault(cond.table_name, set()).add(chunk_index)
            if chunk.label:
                meta.chunk_labels.setdefault(cond.table_name, {})[
                    chunk_index
                ] = chunk.label
            try:
                self.resume_mgr.save(meta)
            except Exception as exc:
                self.logger.warning("保存断点失败: %s", exc)

            completed_chunks_count += 1
            completed_across += 1

            # 进度回调
            if self.progress_callback is not None:
                progress = ChunkProgress(
                    table_name=cond.table_name,
                    chunk_index=chunk_index,
                    total_table_chunks=total_chunks,
                    total_across_all_tables=total_across_all,
                    completed_across_all_tables=(
                        completed_across + completed_chunks_count
                    ),
                    rows=rows_in_chunk,
                )
                try:
                    self.progress_callback(progress)
                except Exception as exc:
                    self.logger.warning("进度回调异常: %s", exc)

            # 清理分块临时文件（CSV 模式）
            if temp_dir is not None:
                chunk_dir = os.path.join(
                    temp_dir,
                    cond.table_name,
                    f"chunk_{chunk_index:06d}",
                )
                self._cleanup_chunk_dir(chunk_dir)

        success = not last_error
        return TableMigrationResult(
            table_name=cond.table_name,
            success=success,
            total_rows=total_rows,
            total_chunks=total_chunks,
            completed_chunks=completed_chunks_count,
            error=last_error,
        )

    # ------------------------------------------------------------------
    # TRUNCATE 策略
    # ------------------------------------------------------------------

    def _resolve_truncate(self, is_first_chunk: bool) -> bool:
        """判断当前分块是否应执行 TRUNCATE。

        - 全新迁移 + truncate_before=True + 首个分块 → truncate
        - 续传模式 → 永不 truncate（数据已存在）
        """
        if self.resume_from is not None:
            return False
        return self.truncate_before and is_first_chunk

    def _truncate_target(self, dst_client: Any, target_table: str) -> None:
        """Truncate target table before migrating first chunk."""
        self.logger.info("TRUNCATE 目标表 %s.%s", self.dst_schema, target_table)
        if self.dst_adapter.db_type == "postgresql":
            from psycopg2 import sql as psql

            with dst_client.cursor() as cursor:
                cursor.execute(
                    psql.SQL("TRUNCATE TABLE {}.{}").format(
                        psql.Identifier(self.dst_schema),
                        psql.Identifier(target_table),
                    )
                )
            dst_client.commit()
        elif self.dst_adapter.db_type == "clickhouse":
            db_name = self.dst_config.get("database", "")
            if db_name:
                full_table = f"`{db_name}`.`{target_table}`"
            else:
                full_table = f"`{target_table}`"
            dst_client.command(f"TRUNCATE TABLE {full_table}")

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _count_total_chunks(self, client: Any) -> int:
        """预先计算所有表的总分块数（用于进度回传）。"""
        total = 0
        for cond in self.conditions:
            if not cond.enabled:
                continue
            try:
                chunks = self._compute_chunks(client, cond)
                total += len(chunks)
            except Exception as exc:
                self.logger.warning("计算表 %s 分块数时出错: %s", cond.table_name, exc)
                total += 1  # 至少一个分块
        return total

    @staticmethod
    def _count_completed_chunks(meta: MigrationMeta) -> int:
        """统计断点中已完成的跨表总分块数。"""
        return sum(len(v) for v in meta.completed_chunks.values())

    @staticmethod
    def _cleanup_chunk_dir(chunk_dir: str) -> None:
        """清理分块的临时文件目录。"""
        try:
            if os.path.isdir(chunk_dir):
                shutil.rmtree(chunk_dir, ignore_errors=True)
        except Exception:
            pass  # 清理失败不影响主流程

    @staticmethod
    def _cleanup_temp_dir(temp_dir: str | None) -> None:
        """清理迁移临时根目录。"""
        if temp_dir and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _close_client(client: Any, adapter: Any) -> None:
        """安全关闭数据库客户端。"""
        if client is not None:
            try:
                adapter.close_client(client)
            except Exception:
                pass

    @staticmethod
    def _build_result(
        results: list[TableMigrationResult],
        total_rows: int,
    ) -> dict[str, Any]:
        """将结果列表组装为兼容 migrate_tables() 的返回字典。"""
        migrated: list[dict[str, Any]] = [
            {"name": r.table_name, "rows": r.total_rows}
            for r in results
            if r.success
        ]
        errors: list[dict[str, str]] = [
            {"name": r.table_name, "error": r.error}
            for r in results
            if not r.success
        ]
        all_success = all(r.success for r in results) if results else False
        return {
            "success": all_success,
            "migrated_tables": migrated,
            "error_tables": errors,
            "total_rows": total_rows,
        }
