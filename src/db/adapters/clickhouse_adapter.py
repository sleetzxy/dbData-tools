"""ClickHouse adapter: CSV flows and SQL export via ``clickhouse_connect``."""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

from core.importer_csv import generate_copy_commands, read_sql_from_file
from db.exceptions import ClientCapabilityError


class ClickHouseAdapter:
    """Backend implementation for ClickHouse ``DatabaseAdapter`` workflows."""

    db_type = "clickhouse"

    def get_table_columns(
        self, client: Any, table: str, database: str = "",
    ) -> list[str]:
        table_str = self._validate_identifier(table, "table")
        db_name = (
            self._validate_identifier(database, "database")
            if database
            else client.database
        )
        result = client.query(
            "SELECT name FROM system.columns "
            "WHERE database = %(database)s AND table = %(table)s "
            "ORDER BY position",
            parameters={"database": db_name, "table": table_str},
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
        """Execute query, return (columns, batch iterator).

        ``clickhouse-connect`` does not support server-side cursors, so the
        entire result set is loaded into memory and then sliced into batches.

        :param client: Open ``clickhouse_connect`` client.
        :param query: SQL SELECT statement.
        :param batch_size: Number of rows per batch (default 10 000).
        :returns: ``(columns, batch_iterator)`` where each batch is a list of
            row tuples.
        """
        result = client.query(query)
        columns = list(result.column_names)
        all_rows: list[tuple] = list(result.result_rows)

        def _batches() -> Iterator[list[tuple]]:
            for i in range(0, len(all_rows), batch_size):
                yield all_rows[i:i + batch_size]

        return columns, _batches()

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
