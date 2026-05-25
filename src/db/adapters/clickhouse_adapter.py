"""ClickHouse adapter: CSV flows and SQL export via ``clickhouse_connect``."""

from __future__ import annotations

import csv
import io
import os
import re
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

from core.importer_csv import generate_copy_commands, read_sql_from_file
from db.exceptions import ClientCapabilityError


_DEFAULT_REMOTE_SETTINGS: dict[str, Any] = {
    "max_execution_time": 0,
    "connect_timeout_with_failover_ms": 3000,
    "receive_timeout": 3600,
    "send_timeout": 3600,
}


class ClickHouseAdapter:
    """Backend implementation for ClickHouse ``DatabaseAdapter`` workflows."""

    db_type = "clickhouse"

    def get_table_columns(
        self, client: Any, table: str, schema: str = "",
    ) -> list[str]:
        table_str = self._validate_identifier(table, "table")
        db_name = (
            self._validate_identifier(schema, "database")
            if schema
            else client.database
        )
        result = client.query(
            "SELECT name FROM system.columns "
            "WHERE database = %(database)s AND table = %(table)s "
            "ORDER BY position",
            parameters={"database": db_name, "table": table_str},
        )
        return [row[0] for row in result.result_rows]

    def list_partitions(
        self,
        client: Any,
        parent_table: str,
        schema: str = "",
    ) -> list[str]:
        """Return distinct partition ids for ``parent_table`` from system.parts."""
        table_str = self._validate_identifier(parent_table, "table")
        db_name = (
            self._validate_identifier(schema, "database")
            if schema
            else client.database
        )
        result = client.query(
            "SELECT DISTINCT partition FROM system.parts "
            "WHERE database = %(db)s AND table = %(table)s",
            parameters={"db": db_name, "table": table_str},
        )
        return [row[0] for row in result.result_rows]

    @classmethod
    def _validate_identifier(cls, name: str, label: str) -> str:
        cleaned = name.strip()
        if not cleaned or "\x00" in cleaned:
            raise ValueError(f"Invalid {label} identifier: {name}")
        return cleaned

    @staticmethod
    def _quote_identifier(name: str) -> str:
        return f"`{name.replace('`', '``')}`"

    def _qualified_table(self, database: str, table_name: str) -> str:
        """Return ``database.table`` with each segment quoted."""
        return (
            f"{self._quote_identifier(database)}.{self._quote_identifier(table_name)}"
        )

    def create_client(self, db_config: dict[str, Any]) -> Any:
        """Build a ``clickhouse_connect`` client for ``db_config``."""
        import clickhouse_connect

        return clickhouse_connect.get_client(
            host=db_config["host"],
            port=db_config["port"],
            username=db_config["user"],
            password=db_config["password"],
            database=db_config["database"],
        )

    def close_client(self, client: Any) -> None:
        """Shut down ``client`` using ``close`` or ``disconnect`` when present."""
        if hasattr(client, "close"):
            client.close()
            return
        if hasattr(client, "disconnect"):
            client.disconnect()

    def stream_read(
        self,
        client: Any,
        query: str,
        batch_size: int = 10000,
    ) -> tuple[list[str], Iterator[list[tuple]]]:
        """Execute query via ``raw_stream`` and yield CSV rows in batches.

        Uses ``FORMAT CSVWithNames`` and parses the byte stream incrementally
        so the full result set is never loaded into memory.

        :param client: Open ``clickhouse_connect`` client with ``raw_stream``.
        :param query: SQL SELECT statement (without ``FORMAT`` clause).
        :param batch_size: Number of rows per batch (default 10 000).
        :returns: ``(columns, batch_iterator)`` where each batch is a list of
            row tuples.
        :raises ClientCapabilityError: When ``client`` lacks ``raw_stream``.
        """
        if not hasattr(client, "raw_stream"):
            raise ClientCapabilityError(
                "ClickHouse client does not support raw_stream; "
                "streaming read requires raw_stream."
            )

        csv_query = f"{query.rstrip().rstrip(';')} FORMAT CSVWithNames"
        stream = client.raw_stream(csv_query)
        text_io = io.TextIOWrapper(stream, encoding="utf-8", newline="")
        reader = csv.reader(text_io)
        columns = next(reader)

        def _batches() -> Iterator[list[tuple]]:
            batch: list[tuple] = []
            try:
                for row in reader:
                    batch.append(tuple(row))
                    if len(batch) >= batch_size:
                        yield batch
                        batch = []
                if batch:
                    yield batch
            finally:
                if hasattr(stream, "close"):
                    stream.close()

        return columns, _batches()

    def stream_write(
        self,
        client: Any,
        table: str,
        columns: list[str],
        rows_iter: Iterator[list[tuple]],
        schema: str = "",
    ) -> int:
        """Consume row batches and INSERT into target table via VALUES.

        :param client: Open ``clickhouse_connect`` client.
        :param table: Target table name.
        :param columns: Column names to insert into.
        :param rows_iter: Iterator yielding batches of row tuples.
        :param schema: Database name (falls back to ``client.database``).
        :returns: Total number of rows inserted.
        """
        total = 0
        db_name = schema or client.database
        full_table = self._qualified_table(db_name, table)
        col_str = ", ".join(self._quote_identifier(c) for c in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        for batch in rows_iter:
            if not batch:
                continue
            values = ", ".join(f"({placeholders})" for _ in batch)
            flat_values = [v for row in batch for v in row]
            client.command(
                f"INSERT INTO {full_table} ({col_str}) VALUES {values}",
                flat_values,
            )
            total += len(batch)
        return total

    @staticmethod
    def _escape_ch_string(value: str) -> str:
        """Escape a string for use inside ClickHouse single-quoted literals."""
        return value.replace("\\", "\\\\").replace("'", "\\'")

    @staticmethod
    def _format_setting_value(value: Any) -> str:
        """Format a ClickHouse SETTINGS value."""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("'", "\\'")
        return f"'{escaped}'"

    def _format_settings_clause(self, settings: dict[str, Any]) -> str:
        """Return ``SETTINGS k=v, ...`` suffix for remote transfer SQL."""
        parts = [
            f"{key}={self._format_setting_value(val)}"
            for key, val in settings.items()
        ]
        return f"SETTINGS {', '.join(parts)}"

    @staticmethod
    def _split_select_from(select_sql: str) -> tuple[str, str]:
        """Split ``SELECT ... FROM ...`` into select clause and FROM remainder."""
        match = re.search(r"\bFROM\b", select_sql, flags=re.IGNORECASE)
        if match is None:
            raise ValueError("select_sql must contain a FROM clause")
        select_clause = select_sql[: match.start()].strip()
        from_and_rest = select_sql[match.end() :].strip()
        if not select_clause.upper().startswith("SELECT"):
            raise ValueError("select_sql must start with SELECT")
        return select_clause, from_and_rest

    @staticmethod
    def _parse_from_rest(from_and_rest: str) -> tuple[str, str]:
        """Return ``(table_ref, suffix)`` from a FROM remainder."""
        suffix_match = re.search(
            r"\s+(?:PARTITION\s+|WHERE\s|ORDER\s|GROUP\s|HAVING\s|LIMIT\s|"
            r"SETTINGS\s)",
            from_and_rest,
            flags=re.IGNORECASE,
        )
        if suffix_match is None:
            return from_and_rest.strip(), ""
        return (
            from_and_rest[: suffix_match.start()].strip(),
            from_and_rest[suffix_match.start() :].strip(),
        )

    @staticmethod
    def _extract_table_name(table_ref: str) -> str:
        """Extract bare table name from ``db.table`` or quoted identifiers."""
        cleaned = table_ref.strip()
        if "." in cleaned:
            cleaned = cleaned.rsplit(".", maxsplit=1)[-1]
        return cleaned.strip("`")

    @staticmethod
    def _append_partition(table_ref: str, partition: str | None) -> str:
        """Append ``PARTITION 'name'`` after a table or remote() expression."""
        if not partition:
            return table_ref
        return f"{table_ref} PARTITION '{partition}'"

    def _apply_partition_to_select(
        self,
        select_sql: str,
        partition: str | None,
    ) -> str:
        """Return ``select_sql`` with ``PARTITION`` injected after the table."""
        if not partition:
            return select_sql
        select_clause, from_and_rest = self._split_select_from(select_sql)
        table_ref, suffix = self._parse_from_rest(from_and_rest)
        if re.search(r"\bPARTITION\b", suffix, flags=re.IGNORECASE):
            return select_sql
        from_source = self._append_partition(table_ref, partition)
        return f"{select_clause} FROM {from_source} {suffix}".strip()

    def _build_pull_select(
        self,
        select_sql: str,
        src_config: dict[str, Any],
        partition: str | None,
    ) -> str:
        """Build inner SELECT using ``remote()`` as the data source."""
        select_clause, from_and_rest = self._split_select_from(select_sql)
        table_ref, suffix = self._parse_from_rest(from_and_rest)
        table_name = self._extract_table_name(table_ref)
        host_port = f"{src_config['host']}:{src_config['port']}"
        database = str(src_config["database"])
        user = self._escape_ch_string(str(src_config["user"]))
        password = self._escape_ch_string(str(src_config["password"]))
        remote_from = (
            f"remote('{host_port}', '{database}', '{table_name}', "
            f"'{user}', '{password}')"
        )
        remote_from = self._append_partition(remote_from, partition)
        return f"{select_clause} FROM {remote_from} {suffix}".strip()

    @staticmethod
    def _client_connection_config(client: Any) -> dict[str, Any]:
        """Extract connection fields from a ``clickhouse_connect`` client."""
        return {
            "host": getattr(client, "host", "localhost"),
            "port": getattr(client, "port", 8123),
            "user": getattr(client, "username", getattr(client, "user", "default")),
            "password": getattr(client, "password", ""),
            "database": getattr(client, "database", "default"),
        }

    def build_remote_insert_sql(
        self,
        src_config: dict[str, Any],
        dst_table: str,
        select_sql: str,
        schema: str = "",
        pull: bool = True,
        settings: dict[str, Any] | None = None,
        dst_config: dict[str, Any] | None = None,
        partition: str | None = None,
    ) -> str:
        """Build INSERT SQL for CK→CK server-side ``remote()`` transfer.

        Pull mode (default): target server pulls from source via ``remote()``.
        Push mode: source server pushes into ``remote()`` function target.

        :param src_config: Source connection config (host, port, user, etc.).
        :param dst_table: Destination table name.
        :param select_sql: Inner SELECT without INSERT wrapper.
        :param schema: Destination database name.
        :param pull: When ``True`` use pull mode; otherwise push mode.
        :param settings: Optional ClickHouse SETTINGS overrides.
        :param dst_config: Destination config (required for push mode).
        :param partition: Optional physical partition name.
        :returns: Complete INSERT statement with SETTINGS clause.
        """
        merged_settings = {**_DEFAULT_REMOTE_SETTINGS, **(settings or {})}
        settings_clause = self._format_settings_clause(merged_settings)

        if pull:
            dst_db = schema or str(src_config.get("database", ""))
            qualified_dst = self._qualified_table(dst_db, dst_table)
            inner_select = self._build_pull_select(
                select_sql, src_config, partition,
            )
            return f"INSERT INTO {qualified_dst} {inner_select} {settings_clause}"

        if dst_config is None:
            raise ValueError("dst_config is required when pull=False")

        dst_db = schema or str(dst_config.get("database", ""))
        qualified_dst = f"{dst_db}.{dst_table}"
        host_port = f"{dst_config['host']}:{dst_config['port']}"
        user = self._escape_ch_string(str(dst_config["user"]))
        password = self._escape_ch_string(str(dst_config["password"]))
        remote_target = (
            f"remote('{host_port}', '{qualified_dst}', '{user}', '{password}')"
        )
        inner_select = self._apply_partition_to_select(select_sql, partition)
        return (
            f"INSERT INTO FUNCTION {remote_target} {inner_select} {settings_clause}"
        )

    @staticmethod
    def _extract_written_rows(result: Any) -> int | None:
        """Try to read affected row count from a command/query result."""
        if result is None:
            return None
        if isinstance(result, int):
            return result
        written = getattr(result, "written_rows", None)
        if written is not None:
            return int(written)
        summary = getattr(result, "summary", None)
        if summary is not None:
            summary_written = getattr(summary, "written_rows", None)
            if summary_written is not None:
                return int(summary_written)
        return None

    def _count_select_rows(self, client: Any, select_sql: str) -> int:
        """Return ``count()`` for an inner SELECT subquery."""
        count_sql = f"SELECT count() FROM ({select_sql}) AS _cnt"
        result = client.query(count_sql)
        if hasattr(result, "result_rows"):
            return int(result.result_rows[0][0])
        if hasattr(result, "result_set"):
            return int(result.result_set[0][0])
        return int(str(result).strip())

    def remote_transfer(
        self,
        dst_client: Any,
        src_config: dict[str, Any],
        dst_table: str,
        select_sql: str,
        schema: str = "",
        pull: bool = True,
        settings: dict[str, Any] | None = None,
        physical_partitions: list[str] | None = None,
    ) -> int:
        """Transfer rows CK→CK via server-side ``remote()`` INSERT SELECT.

        :param dst_client: Destination ClickHouse client (used in pull mode).
        :param src_config: Source connection config dict.
        :param dst_table: Destination table name.
        :param select_sql: Inner SELECT without INSERT wrapper.
        :param schema: Destination database name.
        :param pull: When ``True`` target pulls from source; else source pushes.
        :param settings: Optional ClickHouse SETTINGS overrides.
        :param physical_partitions: When set, run one INSERT per partition.
        :returns: Total rows transferred.
        """
        partitions: list[str | None] = (
            list(physical_partitions) if physical_partitions else [None]
        )
        total = 0
        dst_config = self._client_connection_config(dst_client)

        if pull:
            exec_client = dst_client
        else:
            exec_client = self.create_client(src_config)

        try:
            for partition in partitions:
                sql = self.build_remote_insert_sql(
                    src_config=src_config,
                    dst_table=dst_table,
                    select_sql=select_sql,
                    schema=schema,
                    pull=pull,
                    settings=settings,
                    dst_config=dst_config,
                    partition=partition,
                )
                result = exec_client.command(sql)
                written = self._extract_written_rows(result)
                if written is not None:
                    total += written
                    continue

                count_sql = (
                    self._build_pull_select(select_sql, src_config, partition)
                    if pull
                    else self._apply_partition_to_select(select_sql, partition)
                )
                total += self._count_select_rows(exec_client, count_sql)
        finally:
            if not pull:
                self.close_client(exec_client)

        return total

    def _backup_tables(
        self,
        client: Any,
        database: str,
        table_names: list[str],
        backup_dir: str,
        logger: Any | None = None,
    ) -> str:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = os.path.join(backup_dir, timestamp)
        os.makedirs(backup_path, exist_ok=True)

        for table in table_names:
            table_name = self._validate_identifier(str(table).strip(), "table")
            qualified = self._qualified_table(database, table_name)
            backup_file = os.path.join(backup_path, f"{table_name}.csv")
            query = f"SELECT * FROM {qualified} FORMAT CSVWithNames"

            if logger:
                msg = f"\u6b63\u5728\u5907\u4efd\u8868 {database}.{table_name}"
                logger.info("%s -> %s", msg, backup_file)

            if hasattr(client, "raw_stream"):
                stream = client.raw_stream(query)
                try:
                    with open(backup_file, "wb") as f:
                        while True:
                            chunk = stream.read(1024 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
                finally:
                    if hasattr(stream, "close"):
                        stream.close()
            elif hasattr(client, "raw_query"):
                response = client.raw_query(query)
                data = (
                    response
                    if isinstance(response, bytes)
                    else str(response).encode("utf-8")
                )
                with open(backup_file, "wb") as f:
                    f.write(data)
            else:
                raise ClientCapabilityError(
                    "ClickHouse client does not support raw backup query"
                )

        return backup_path

    @staticmethod
    def _format_chunk_value(value: Any) -> str:
        """Format a chunk bound value as a SQL literal for inline use.

        :param value: Integer, string, datetime, or ``None``.
        :returns: SQL-safe literal string.
        """
        if value is None:
            return "NULL"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        if isinstance(value, datetime):
            return f"'{value.isoformat()}'"
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

    def _build_chunked_query(
        self,
        table: str,
        schema: str,
        where_clause: str = "",
        custom_sql: str = "",
        chunk_key: str = "",
        chunk_start: Any = None,
        chunk_end: Any = None,
    ) -> str:
        """Build a SELECT SQL string for chunked/conditional ClickHouse export.

        SQL construction priority:

        1. ``custom_sql`` + chunk: wrap custom SQL as subquery, add chunk range
        2. ``where_clause`` + chunk:
           ``SELECT * FROM db.t WHERE key>=s AND key<e AND cond``
        3. chunk only: ``SELECT * FROM db.t WHERE key>=s AND key<e``
        4. neither: full table ``SELECT * FROM db.t``

        :returns: SELECT query string (without ``FORMAT`` clause).
        """
        has_chunk = bool(chunk_key) and (
            chunk_start is not None or chunk_end is not None
        )
        database = schema if schema else ""

        # Priority 1: custom_sql
        if custom_sql:
            query = f"SELECT * FROM ({custom_sql}) AS _sub"
            if has_chunk:
                conditions = []
                if chunk_start is not None:
                    conditions.append(
                        f"{self._quote_identifier(chunk_key)}"
                        f" >= {self._format_chunk_value(chunk_start)}"
                    )
                if chunk_end is not None:
                    conditions.append(
                        f"{self._quote_identifier(chunk_key)}"
                        f" < {self._format_chunk_value(chunk_end)}"
                    )
                query = f"{query} WHERE {' AND '.join(conditions)}"
                query = f"{query} ORDER BY {self._quote_identifier(chunk_key)}"
            return query

        # Base: SELECT * FROM database.table
        qualified = self._qualified_table(database, table)
        query = f"SELECT * FROM {qualified}"

        conditions: list[str] = []

        # Chunk conditions (Priorities 2 & 3)
        if has_chunk:
            if chunk_start is not None:
                conditions.append(
                    f"{self._quote_identifier(chunk_key)}"
                    f" >= {self._format_chunk_value(chunk_start)}"
                )
            if chunk_end is not None:
                conditions.append(
                    f"{self._quote_identifier(chunk_key)}"
                    f" < {self._format_chunk_value(chunk_end)}"
                )

        # WHERE clause (Priority 2)
        if where_clause:
            conditions.append(f"({where_clause})")

        if conditions:
            query = f"{query} WHERE {' AND '.join(conditions)}"

        if has_chunk:
            query = f"{query} ORDER BY {self._quote_identifier(chunk_key)}"

        return query

    def export_csv(
        self,
        client: Any,
        db_config: dict[str, Any],
        table: str,
        export_dir: str,
        schema: str = "",
        include_header: bool = True,
        where_clause: str = "",
        custom_sql: str = "",
        chunk_key: str = "",
        chunk_start: Any = None,
        chunk_end: Any = None,
        logger: Any | None = None,
    ) -> dict[str, Any]:
        """Stream a single table to a CSV file using ``raw_stream`` / ``raw_query``."""
        database = self._validate_identifier(
            str(db_config.get("database", "")).strip(), "database"
        )
        result = {
            "success": True,
            "exported_tables": [],
            "error_tables": [],
            "total_rows": 0,
            "schema": "",
        }

        os.makedirs(export_dir, exist_ok=True)

        try:
            table_name = self._validate_identifier(str(table).strip(), "table")
            output_file = os.path.join(export_dir, f"{table_name}.csv")
            if logger:
                logger.info(
                    f"Exporting table {database}.{table_name} -> {output_file}"
                )

            select_query = self._build_chunked_query(
                table=table_name,
                schema=database,
                where_clause=where_clause,
                custom_sql=custom_sql,
                chunk_key=chunk_key,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
            )

            format_name = "CSVWithNames" if include_header else "CSV"
            query = f"{select_query} FORMAT {format_name}"

            if hasattr(client, "raw_stream"):
                stream = client.raw_stream(query)
                try:
                    with open(output_file, "wb") as f:
                        while True:
                            chunk = stream.read(1024 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
                finally:
                    if hasattr(stream, "close"):
                        stream.close()
            else:
                response = client.raw_query(query)
                if isinstance(response, bytes):
                    csv_text = response.decode("utf-8")
                else:
                    csv_text = str(response)
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(csv_text)

            row_count = 0
            if hasattr(client, "query"):
                count_query = (
                    f"SELECT count() FROM ({select_query}) AS _cnt"
                )
                count_result = client.query(count_query)
                if hasattr(count_result, "result_rows"):
                    row_count = count_result.result_rows[0][0]
                elif hasattr(count_result, "result_set"):
                    row_count = count_result.result_set[0][0]
                else:
                    row_count = int(str(count_result).strip())

            result["total_rows"] += row_count
            result["exported_tables"].append(
                {
                    "schema": "",
                    "name": table_name,
                    "rows": row_count,
                    "file": output_file,
                }
            )

            if logger:
                logger.info(
                    "Export finished for %s.%s, rows: %s",
                    database,
                    table_name,
                    row_count,
                )
        except Exception as exc:
            error_msg = f"Export failed for {database}.{table}: {exc}"
            if logger:
                logger.error(error_msg)
            result["error_tables"].append(
                {
                    "schema": "",
                    "name": table,
                    "error": str(exc),
                }
            )
            result["success"] = False

        return result

    def import_csv(
        self,
        client: Any,
        db_config: dict[str, Any],
        table_names: list[str],
        data_dir: str,
        schema: str = "",
        pre_sql_file: str = "",
        need_backup: bool = False,
        truncate_before: bool = True,
        is_first_chunk: bool = False,
        logger: Any | None = None,
    ) -> dict[str, Any]:
        """Load CSV files via ``INSERT ... FORMAT CSVWithNames``.

        :param is_first_chunk: When ``True`` and ``truncate_before`` is also
            ``True``, truncate the target table before importing (first chunk
            of a migration). When ``False`` (default), skip truncation even if
            ``truncate_before`` is set, so subsequent chunks can append data.
        """
        database = self._validate_identifier(
            str(db_config.get("database", "")).strip(), "database"
        )
        result = {
            "success": True,
            "imported_tables": [],
            "error_tables": [],
            "backup_path": None,
            "data_directory": data_dir,
            "schema": "",
        }
        if not table_names:
            result["success"] = False
            result["error"] = "\u672a\u627e\u5230\u9700\u8981\u5bfc\u5165\u7684\u8868"
            return result

        if pre_sql_file:
            try:
                pre_sql = read_sql_from_file(pre_sql_file)
                for statement in self._split_sql_statements(pre_sql):
                    if logger:
                        logger.info(
                            f"\u6267\u884c\u9884\u5904\u7406 SQL: {statement[:100]}"
                        )
                    if hasattr(client, "command"):
                        client.command(statement)
            except Exception as exc:
                error_msg = f"\u6267\u884c\u9884\u5904\u7406 SQL \u5931\u8d25: {exc}"
                if logger:
                    logger.error(error_msg)
                result["success"] = False
                result["error"] = error_msg
                return result

        if need_backup:
            try:
                backup_dir = os.path.join(data_dir, "backup")
                result["backup_path"] = self._backup_tables(
                    client=client,
                    database=database,
                    table_names=table_names,
                    backup_dir=backup_dir,
                    logger=logger,
                )
            except Exception as exc:
                error_msg = f"\u5bfc\u5165\u524d\u5907\u4efd\u5931\u8d25: {exc}"
                if logger:
                    logger.error(error_msg)
                result["success"] = False
                result["error"] = error_msg
                return result

        copy_commands = generate_copy_commands(table_names, data_dir)

        for table, csv_file in copy_commands:
            try:
                table_name = self._validate_identifier(str(table).strip(), "table")
                qualified = self._qualified_table(database, table_name)
                if logger:
                    msg = (
                        f"\u6b63\u5728\u5bfc\u5165 {database}.{table_name} "
                        f"<- {csv_file}"
                    )
                    logger.info(msg)
                if hasattr(client, "command"):
                    if truncate_before and is_first_chunk:
                        client.command(f"TRUNCATE TABLE {qualified}")
                    with open(csv_file, "rb") as f:
                        data = f.read()
                        client.command(
                            f"INSERT INTO {qualified} FORMAT CSVWithNames",
                            data=data,
                        )
                else:
                    raise ClientCapabilityError(
                        "ClickHouse client does not support command()"
                    )

                result["imported_tables"].append(table_name)
                if logger:
                    logger.info(
                        f"\u8868 {database}.{table_name} \u5bfc\u5165\u5b8c\u6210"
                    )
            except Exception as exc:
                error_msg = f"\u5bfc\u5165 {database}.{table} \u5931\u8d25: {exc}"
                if logger:
                    logger.error(error_msg)
                result["error_tables"].append({"table": table, "error": str(exc)})
                result["success"] = False

        return result

    @staticmethod
    def _split_sql_statements(sql_text: str) -> list[str]:
        statements: list[str] = []
        buffer: list[str] = []
        i = 0
        in_single = False
        in_double = False
        in_line_comment = False
        in_block_comment = False

        while i < len(sql_text):
            ch = sql_text[i]
            nxt = sql_text[i + 1] if i + 1 < len(sql_text) else ""

            if in_line_comment:
                if ch == "\n":
                    in_line_comment = False
                    buffer.append(ch)
                i += 1
                continue

            if in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if not in_single and not in_double and ch == "-" and nxt == "-":
                in_line_comment = True
                i += 2
                continue

            if not in_single and not in_double and ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue

            if not in_double and ch == "'":
                if in_single and nxt == "'":
                    buffer.append(ch)
                    buffer.append(nxt)
                    i += 2
                    continue
                in_single = not in_single
                buffer.append(ch)
                i += 1
                continue

            if not in_single and ch == '"':
                in_double = not in_double
                buffer.append(ch)
                i += 1
                continue

            if ch == ";" and not in_single and not in_double:
                statement = "".join(buffer).strip()
                if statement:
                    statements.append(statement)
                buffer = []
                i += 1
                continue

            buffer.append(ch)
            i += 1

        trailing = "".join(buffer).strip()
        if trailing:
            statements.append(trailing)

        return statements

    def export_sql(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Emit DDL and row ``INSERT`` statements for all tables in a database."""
        client = kwargs.get("client")
        db_config = kwargs.get("db_config", {})
        export_dir = kwargs.get("export_dir")
        exclude_tables = kwargs.get("exclude_tables") or []
        include_truncate = kwargs.get("include_truncate", True)
        logger = kwargs.get("logger")

        if export_dir is None or not str(export_dir).strip():
            return {
                "success": False,
                "error": "export_dir is required",
                "schema": "",
            }
        export_dir_str = str(export_dir)
        if client is None:
            return {
                "success": False,
                "error": "client is required",
                "schema": "",
            }
        ch_client = client

        database = self._validate_identifier(
            str(db_config.get("database", "")).strip(), "database"
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file = os.path.join(export_dir_str, f"{database}_{timestamp}.sql")

        def _extract_rows(result: Any) -> Sequence[tuple[Any, ...]]:
            if hasattr(result, "result_rows"):
                return result.result_rows
            if hasattr(result, "result_set"):
                return result.result_set
            if isinstance(result, list):
                return result
            return []

        def _query(statement: str) -> Sequence[tuple[Any, ...]]:
            if hasattr(ch_client, "query"):
                return _extract_rows(ch_client.query(statement))
            if hasattr(ch_client, "raw_query"):
                response = ch_client.raw_query(statement)
                if isinstance(response, (list, tuple)):
                    return response
                return []
            raise ClientCapabilityError("ClickHouse client does not support query")

        def _serialize_value(value: Any) -> str:
            if value is None:
                return "NULL"
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, (int, float)):
                return str(value)
            value_str = str(value).replace("'", "''")
            return f"'{value_str}'"

        try:
            tables_rows = _query(f"SHOW TABLES FROM {self._quote_identifier(database)}")
            tables = [str(row[0]) for row in tables_rows if row]

            if exclude_tables:
                exclude_set = {str(name) for name in exclude_tables}
                tables = [t for t in tables if t not in exclude_set]

            tables = sorted(tables)

            if not tables:
                return {
                    "success": False,
                    "error": "No exportable tables found",
                    "schema": "",
                }

            os.makedirs(os.path.dirname(os.path.abspath(export_file)), exist_ok=True)

            with open(export_file, "w", encoding="utf-8") as f:
                f.write("-- ClickHouse SQL export\n")
                f.write(f"-- database: {database}\n\n")

                for table in tables:
                    table_name = self._validate_identifier(table, "table")
                    qualified = self._qualified_table(database, table_name)

                    if logger:
                        logger.info(f"Exporting table {database}.{table_name}")

                    ddl_rows = _query(f"SHOW CREATE TABLE {qualified}")
                    if ddl_rows:
                        ddl = str(ddl_rows[0][0]).strip()
                        if not ddl.endswith(";"):
                            ddl = f"{ddl};"
                        f.write(f"{ddl}\n")

                    if include_truncate:
                        f.write(f"TRUNCATE TABLE {qualified};\n")

                    if hasattr(ch_client, "query"):
                        data_result = ch_client.query(f"SELECT * FROM {qualified}")
                        rows = _extract_rows(data_result)
                        column_names = []
                        if hasattr(data_result, "column_names"):
                            column_names = list(data_result.column_names or [])
                    else:
                        rows = _query(f"SELECT * FROM {qualified}")
                        column_names = []

                    if rows:
                        if not column_names:
                            column_names = [f"col{i + 1}" for i in range(len(rows[0]))]
                        columns_str = ", ".join(
                            self._quote_identifier(name) for name in column_names
                        )
                        for row in rows:
                            values_str = ", ".join(
                                _serialize_value(value) for value in row
                            )
                            insert_line = (
                                f"INSERT INTO {qualified} ({columns_str}) "
                                f"VALUES ({values_str});\n"
                            )
                            f.write(insert_line)

                    f.write("\n")

            return {"success": True, "schema": "", "export_file": export_file}
        except Exception as exc:
            if logger:
                logger.error(f"Export failed: {exc}")
            return {"success": False, "error": str(exc), "schema": ""}
