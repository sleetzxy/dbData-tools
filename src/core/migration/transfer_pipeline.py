"""Unified transfer routing for migration chunks."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

from core.migration.models import (
    ChunkSpec,
    MemoryBudgetConfig,
    MigrationCondition,
    TransferMode,
)
from core.migration.memory_budget import MemoryBudget

_DEFAULT_AVG_ROW_BYTES = 1000
_DEFAULT_STREAM_BATCH_ROWS = 10_000


class TransferPipeline:
    """Route chunk transfers by DB pair and transfer mode."""

    def __init__(
        self,
        src_adapter: Any,
        dst_adapter: Any,
        src_config: dict[str, Any],
        dst_config: dict[str, Any],
        src_schema: str,
        dst_schema: str,
        transfer_mode: TransferMode = TransferMode.STREAM,
        memory_budget: MemoryBudget | None = None,
        logger: Any | None = None,
    ) -> None:
        self.src_adapter = src_adapter
        self.dst_adapter = dst_adapter
        self.src_config = src_config
        self.dst_config = dst_config
        self.src_schema = src_schema
        self.dst_schema = dst_schema
        self.transfer_mode = transfer_mode
        self.memory_budget = memory_budget or MemoryBudget(MemoryBudgetConfig())
        self.logger = logger or logging.getLogger("migrate.pipeline")

    def transfer_chunk(
        self,
        src_client: Any,
        dst_client: Any,
        cond: MigrationCondition,
        chunk: ChunkSpec,
        target_table: str,
        truncate: bool = False,
        temp_dir: str | None = None,
    ) -> int:
        """Transfer one chunk from source to destination.

        :param temp_dir: Optional root directory for CSV mode exports.
        :return: Number of rows transferred.
        """
        if self.transfer_mode == TransferMode.CSV:
            return self._transfer_csv(
                src_client=src_client,
                dst_client=dst_client,
                cond=cond,
                chunk=chunk,
                target_table=target_table,
                truncate=truncate,
                temp_dir=temp_dir,
            )
        return self._transfer_stream(
            src_client=src_client,
            dst_client=dst_client,
            cond=cond,
            chunk=chunk,
            target_table=target_table,
        )

    def _transfer_csv(
        self,
        src_client: Any,
        dst_client: Any,
        cond: MigrationCondition,
        chunk: ChunkSpec,
        target_table: str,
        truncate: bool,
        temp_dir: str | None,
    ) -> int:
        root_dir = temp_dir or tempfile.mkdtemp(prefix="transfer_chunk_")
        chunk_dir = os.path.join(
            root_dir,
            cond.table_name,
            f"chunk_{chunk.chunk_index:06d}",
        )
        os.makedirs(chunk_dir, exist_ok=True)

        merged_where = self._merge_where_fragments(cond, chunk)
        export_result = self.src_adapter.export_csv(
            client=src_client,
            db_config=self.src_config,
            table=cond.table_name,
            export_dir=chunk_dir,
            schema=self.src_schema,
            include_header=True,
            where_clause=merged_where,
            custom_sql=cond.custom_sql,
            chunk_key=cond.chunk_key,
            chunk_start=chunk.key_start,
            chunk_end=chunk.key_end,
            logger=self.logger,
        )
        if not export_result.get("success"):
            raise RuntimeError(
                f"export_csv failed: {self._extract_error(export_result)}",
            )

        csv_path = os.path.join(chunk_dir, f"{cond.table_name}.csv")
        if not os.path.isfile(csv_path):
            raise FileNotFoundError(f"CSV not found after export: {csv_path}")

        import_result = self.dst_adapter.import_csv(
            client=dst_client,
            db_config=self.dst_config,
            table_names=[target_table],
            data_dir=chunk_dir,
            schema=self.dst_schema,
            truncate_before=truncate,
            is_first_chunk=truncate,
            logger=self.logger,
        )
        if not import_result.get("success"):
            raise RuntimeError(
                f"import_csv failed: {self._extract_error(import_result)}",
            )

        return int(export_result.get("total_rows", 0))

    def _transfer_stream(
        self,
        src_client: Any,
        dst_client: Any,
        cond: MigrationCondition,
        chunk: ChunkSpec,
        target_table: str,
    ) -> int:
        src_type = self.src_adapter.db_type
        dst_type = self.dst_adapter.db_type

        if src_type == "postgresql" and dst_type == "postgresql":
            return self._stream_pg_to_pg(
                src_client, dst_client, cond, chunk, target_table,
            )
        if src_type == "clickhouse" and dst_type == "clickhouse":
            return self._stream_ck_to_ck(
                dst_client, cond, chunk, target_table,
            )
        return self._stream_heterogeneous(
            src_client, dst_client, cond, chunk, target_table,
        )

    def _stream_pg_to_pg(
        self,
        src_client: Any,
        dst_client: Any,
        cond: MigrationCondition,
        chunk: ChunkSpec,
        target_table: str,
    ) -> int:
        query_str = self._build_select_for_chunk(cond, chunk, src_client)
        columns = self.dst_adapter.get_table_columns(
            dst_client, target_table, self.dst_schema,
        )
        return self.src_adapter.copy_stream_transfer(
            src_client,
            dst_client,
            query_str,
            target_table,
            columns,
            self.dst_schema,
            max_buffer_bytes=self.memory_budget.buffer_bytes,
        )

    def _stream_ck_to_ck(
        self,
        dst_client: Any,
        cond: MigrationCondition,
        chunk: ChunkSpec,
        target_table: str,
    ) -> int:
        select_sql = self._build_select_for_chunk(cond, chunk)
        physical_partitions = chunk.physical_targets or None
        return self.src_adapter.remote_transfer(
            dst_client=dst_client,
            src_config=self.src_config,
            dst_table=target_table,
            select_sql=select_sql,
            schema=self.dst_schema,
            pull=True,
            physical_partitions=physical_partitions,
        )

    def _stream_heterogeneous(
        self,
        src_client: Any,
        dst_client: Any,
        cond: MigrationCondition,
        chunk: ChunkSpec,
        target_table: str,
    ) -> int:
        query_str = self._build_select_for_chunk(cond, chunk, src_client)
        batch_size = self.memory_budget.compute_batch_rows(_DEFAULT_AVG_ROW_BYTES)
        col_names, rows_iter = self.src_adapter.stream_read(
            src_client, query_str, batch_size,
        )
        return self.dst_adapter.stream_write(
            dst_client, target_table, col_names, rows_iter, self.dst_schema,
        )

    def _build_select_for_chunk(
        self,
        cond: MigrationCondition,
        chunk: ChunkSpec,
        src_client: Any | None = None,
    ) -> str:
        merged_where = self._merge_where_fragments(cond, chunk)
        if hasattr(self.src_adapter, "_build_chunked_query"):
            query = self.src_adapter._build_chunked_query(
                table=cond.table_name,
                schema=self.src_schema,
                where_clause=merged_where,
                custom_sql=cond.custom_sql,
                chunk_key=cond.chunk_key,
                chunk_start=chunk.key_start,
                chunk_end=chunk.key_end,
            )
            return self._query_to_string(query, src_client)

        table_ref = (
            f"{self.src_schema}.{cond.table_name}"
            if self.src_schema
            else cond.table_name
        )
        if merged_where:
            return f"SELECT * FROM {table_ref} WHERE {merged_where}"
        return f"SELECT * FROM {table_ref}"

    @staticmethod
    def _merge_where_fragments(cond: MigrationCondition, chunk: ChunkSpec) -> str:
        parts: list[str] = []
        if cond.where_clause:
            parts.append(f"({cond.where_clause})")
        if cond.split.extra_where:
            parts.append(f"({cond.split.extra_where})")
        if chunk.where_sql:
            parts.append(f"({chunk.where_sql})")
        return " AND ".join(parts)

    @staticmethod
    def _query_to_string(query: Any, client: Any | None) -> str:
        if hasattr(query, "as_string") and client is not None:
            return query.as_string(client)
        return str(query)

    @staticmethod
    def _extract_error(result: dict[str, Any]) -> str:
        error_msg = result.get("error") or ""
        if error_msg:
            return error_msg
        error_tables = result.get("error_tables") or []
        if error_tables:
            return error_tables[0].get("error", "unknown error")
        return "unknown error"
