"""PostgreSQL adapter: CSV import/export and SQL dump helpers via ``psycopg2``."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import psycopg2
from psycopg2 import sql

from core.importer_csv import generate_copy_commands, read_sql_from_file


def _quote_pg_ident_segment(name: str) -> str:
    """Quote a PostgreSQL identifier for server-side SQL text (not parameters).

    Used when composing COPY text without a live ``psycopg2`` quoting context,
    such as lightweight test doubles.

    :param name: Identifier fragment (schema, table, or column).
    :return: Double-quoted, escaped identifier string.
    """
    return '"' + str(name).replace('"', '""') + '"'


class PostgreSQLAdapter:
    """Backend implementation for PostgreSQL ``DatabaseAdapter`` operations."""

    db_type = "postgresql"

    def create_client(
        self, db_config: dict[str, Any]
    ) -> psycopg2.extensions.connection:
        """Open a ``psycopg2`` connection using normalized ``db_config`` keys."""
        return psycopg2.connect(
            host=db_config["host"],
            port=db_config["port"],
            user=db_config["user"],
            password=db_config["password"],
            database=db_config["database"],
        )

    def close_client(self, client: psycopg2.extensions.connection) -> None:
        """Close ``client`` if it is still open."""
        client.close()

    def get_table_columns(
        self, client: psycopg2.extensions.connection, table: str, schema: str = "public",
    ) -> list[str]:
        cleaned = str(table).strip()
        if not cleaned or "\x00" in cleaned:
            raise ValueError(f"Invalid table identifier: {table}")
        with client.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position",
                (schema, cleaned),
            )
            return [row[0] for row in cursor]

    def stream_read(
        self,
        client: psycopg2.extensions.connection,
        query: str,
        batch_size: int = 10000,
    ) -> tuple[list[str], Iterator[list[tuple]]]:
        """Execute query via server-side cursor, return (columns, batch iterator).

        Uses a named ``psycopg2`` server-side cursor so rows are fetched from
        the database incrementally without loading the entire result set into
        memory at once.

        :param client: Open ``psycopg2`` connection.
        :param query: SQL SELECT statement.
        :param batch_size: Number of rows per batch (default 10 000).
        :returns: ``(columns, batch_iterator)`` where each batch is a list of
            row tuples.
        """
        if not hasattr(self, "_stream_counter"):
            self._stream_counter = 0
        self._stream_counter += 1
        cursor = client.cursor(
            name=f"stream_{id(self)}_{self._stream_counter}",
        )
        cursor.execute(query)
        if cursor.description is None:
            cursor.close()
            raise ValueError(
                "stream_read requires a query that returns rows; "
                "cursor.description is None",
            )
        columns = [desc[0] for desc in cursor.description]

        def _batches() -> Iterator[list[tuple]]:
            try:
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    yield rows
            finally:
                cursor.close()

        return columns, _batches()

    def stream_write(
        self,
        client: psycopg2.extensions.connection,
        table: str,
        columns: list[str],
        rows_iter: Iterator[list[tuple]],
        schema: str = "public",
    ) -> int:
        """Consume row batches and INSERT into target table via execute_values.

        :param client: Open ``psycopg2`` connection.
        :param table: Target table name.
        :param columns: Column names to insert into.
        :param rows_iter: Iterator yielding batches of row tuples.
        :param schema: Schema name (default ``"public"``).
        :returns: Total number of rows inserted.
        """
        from psycopg2.extras import execute_values

        total = 0
        cols_sql = sql.SQL(", ").join(
            sql.Identifier(c) for c in columns
        )
        insert_sql = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s").format(
            sql.Identifier(schema), sql.Identifier(table), cols_sql,
        )
        with client.cursor() as cursor:
            for batch in rows_iter:
                if not batch:
                    continue
                execute_values(cursor, insert_sql, batch)
                total += len(batch)
        client.commit()
        return total

    @staticmethod
    def _get_table_counts(
        client: psycopg2.extensions.connection,
        schema: str,
        table_names: list[str],
        logger: Any | None = None,
    ) -> dict[str, int]:
        if not table_names:
            return {}

        try:
            with client.cursor() as cursor:
                counts: dict[str, int] = {}
                for table in table_names:
                    count_query = sql.SQL("SELECT COUNT(1) FROM {}.{}").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                    )
                    cursor.execute(count_query)
                    row = cursor.fetchone()
                    counts[table] = row[0] if row else 0
                return counts
        except (
            psycopg2.Error,
            AttributeError,
            TypeError,
        ) as exc:
            if logger:
                logger.error(f"Failed to get row counts: {exc}")
            return {}

    @staticmethod
    def _backup_tables(
        client: psycopg2.extensions.connection,
        schema: str,
        table_names: list[str],
        backup_dir: str,
        logger: Any | None = None,
    ) -> str:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = os.path.join(backup_dir, timestamp)
        os.makedirs(backup_path, exist_ok=True)
        if logger:
            logger.info(f"Created backup directory: {backup_path}")

        with client.cursor() as cursor:
            for table in table_names:
                backup_file = os.path.join(backup_path, f"{table}.csv")
                try:
                    with open(backup_file, "w", encoding="utf-8") as f:
                        backup_sql = sql.SQL(
                            "COPY (SELECT * FROM {}.{}) TO STDOUT WITH ("
                            "FORMAT CSV, HEADER true, DELIMITER ',', ENCODING 'UTF8')"
                        ).format(
                            sql.Identifier(schema),
                            sql.Identifier(table),
                        )
                        cursor.copy_expert(backup_sql.as_string(client), f)
                    if logger:
                        logger.info(f"Table {table} backup completed -> {backup_file}")
                except (OSError, psycopg2.Error) as exc:
                    if logger:
                        logger.error(f"Table {table} backup failed: {exc}")

        return backup_path

    @staticmethod
    def _execute_pre_sql(
        client: psycopg2.extensions.connection,
        pre_sql: str,
        logger: Any | None = None,
    ) -> None:
        if not pre_sql.strip():
            if logger:
                logger.info("No pre-SQL provided")
            return

        if logger:
            logger.info("Starting pre-SQL execution")

        def split_sql_statements(sql_text: str) -> list[str]:
            statements: list[str] = []
            buffer: list[str] = []
            i = 0
            in_single = False
            in_double = False
            in_line_comment = False
            in_block_comment = False
            dollar_tag: str | None = None

            def _match_dollar_tag(text: str, start: int) -> str | None:
                if text[start] != "$":
                    return None
                end = text.find("$", start + 1)
                if end == -1:
                    return None
                tag = text[start : end + 1]
                inner = tag[1:-1]
                if inner == "" or inner.replace("_", "").isalnum():
                    return tag
                return None

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

                if dollar_tag is not None:
                    if sql_text.startswith(dollar_tag, i):
                        buffer.append(dollar_tag)
                        i += len(dollar_tag)
                        dollar_tag = None
                        continue
                    buffer.append(ch)
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

                if not in_single and not in_double and ch == "$":
                    tag = _match_dollar_tag(sql_text, i)
                    if tag:
                        dollar_tag = tag
                        buffer.append(tag)
                        i += len(tag)
                        continue

                if ch == ";" and not in_single and not in_double and dollar_tag is None:
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

            return [
                stmt
                for stmt in statements
                if stmt and not stmt.strip().upper().startswith("DELIMITER ")
            ]

        sql_statements = split_sql_statements(pre_sql)

        if logger:
            logger.info(f"Parsed {len(sql_statements)} SQL statements")

        with client.cursor() as cursor:
            for i, sql_statement in enumerate(sql_statements, 1):
                sql_statement = sql_statement.strip()
                if not sql_statement:
                    continue

                try:
                    sql_preview = (
                        sql_statement[:100] + "..."
                        if len(sql_statement) > 100
                        else sql_statement
                    )
                    if logger:
                        logger.info(
                            "Executing SQL statement %s/%s: %s",
                            i,
                            len(sql_statements),
                            sql_preview,
                        )

                    cursor.execute(sql_statement)

                    affected = cursor.rowcount
                    if logger:
                        if affected >= 0:
                            logger.info(
                                f"SQL executed successfully, affected rows: {affected}"
                            )
                        else:
                            logger.info("DDL executed successfully")
                except psycopg2.Error as exc:
                    if logger:
                        stmt_preview = f"{sql_statement[:200]}..."
                        logger.error(
                            "SQL execution failed - statement %s: %s",
                            i,
                            stmt_preview,
                        )
                        logger.error(f"Error details: {str(exc)}")

                    error_str = str(exc).lower()
                    if any(
                        keyword in error_str
                        for keyword in ["already exists", "duplicate", "exists"]
                    ):
                        if logger:
                            logger.warning("Object already exists, skipped current SQL")
                        continue
                    raise

    @staticmethod
    def _build_chunked_query(
        table: str,
        schema: str,
        where_clause: str = "",
        custom_sql: str = "",
        chunk_key: str = "",
        chunk_start: Any = None,
        chunk_end: Any = None,
    ) -> sql.Composed:
        """Build a ``psycopg2.sql.Composed`` SELECT query for chunked/conditional
        export.

        SQL construction priority:

        1. ``custom_sql`` + chunk: wrap custom SQL as subquery, add chunk range
        2. ``where_clause`` + chunk:
           ``SELECT * FROM t WHERE key>=start AND key<end AND cond``
        3. chunk only: ``SELECT * FROM t WHERE key>=start AND key<end``
        4. neither: full table export ``SELECT * FROM t``

        :param table: Table name (trusted identifier).
        :param schema: Schema name (trusted identifier).
        :param where_clause: WHERE fragment without the ``WHERE`` keyword.
        :param custom_sql: Full custom SELECT query.
        :param chunk_key: Column name for chunking.
        :param chunk_start: Chunk lower bound (inclusive).
        :param chunk_end: Chunk upper bound (exclusive).
        :returns: A safe ``Composed`` query object.
        """
        has_chunk = bool(chunk_key) and (
            chunk_start is not None or chunk_end is not None
        )

        # Priority 1: custom_sql
        if custom_sql:
            query = sql.SQL("SELECT * FROM ({}) AS _sub").format(
                sql.SQL(custom_sql),
            )
            if has_chunk:
                conditions = []
                if chunk_start is not None:
                    conditions.append(
                        sql.SQL("{} >= {}").format(
                            sql.Identifier(chunk_key),
                            sql.Literal(chunk_start),
                        )
                    )
                if chunk_end is not None:
                    conditions.append(
                        sql.SQL("{} < {}").format(
                            sql.Identifier(chunk_key),
                            sql.Literal(chunk_end),
                        )
                    )
                query = sql.SQL("{} WHERE {}").format(
                    query,
                    sql.SQL(" AND ").join(conditions),
                )
                query = sql.SQL("{} ORDER BY {}").format(
                    query,
                    sql.Identifier(chunk_key),
                )
            return query

        # Base: SELECT * FROM schema.table
        query = sql.SQL("SELECT * FROM {}.{}").format(
            sql.Identifier(schema),
            sql.Identifier(table),
        )

        conditions: list[sql.Composable] = []

        # Chunk conditions (Priorities 2 & 3)
        if has_chunk:
            if chunk_start is not None:
                conditions.append(
                    sql.SQL("{} >= {}").format(
                        sql.Identifier(chunk_key),
                        sql.Literal(chunk_start),
                    )
                )
            if chunk_end is not None:
                conditions.append(
                    sql.SQL("{} < {}").format(
                        sql.Identifier(chunk_key),
                        sql.Literal(chunk_end),
                    )
                )

        # WHERE clause (Priority 2)
        if where_clause:
            conditions.append(
                sql.SQL("({})").format(sql.SQL(where_clause)),
            )

        if conditions:
            query = sql.SQL("{} WHERE {}").format(
                query,
                sql.SQL(" AND ").join(conditions),
            )

        if has_chunk:
            query = sql.SQL("{} ORDER BY {}").format(
                query,
                sql.Identifier(chunk_key),
            )

        return query

    def export_csv(
        self,
        client: psycopg2.extensions.connection,
        db_config: dict[str, Any],
        table: str,
        export_dir: str,
        schema: str = "public",
        include_header: bool = True,
        where_clause: str = "",
        custom_sql: str = "",
        chunk_key: str = "",
        chunk_start: Any = None,
        chunk_end: Any = None,
        logger: Any | None = None,
    ) -> dict[str, Any]:
        """Export a single ``table`` from ``schema`` into CSV under ``export_dir``."""
        result = {
            "success": True,
            "exported_tables": [],
            "error_tables": [],
            "total_rows": 0,
            "schema": schema,
        }

        cursor = None
        try:
            cursor = client.cursor()

            os.makedirs(export_dir, exist_ok=True)

            cursor.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name = %s",
                (schema,),
            )
            if not cursor.fetchone():
                result["success"] = False
                result["error"] = f"Schema '{schema}' does not exist"
                return result

            try:
                table_str = str(table).strip()
                output_file = os.path.join(export_dir, f"{table_str}.csv")
                if logger:
                    logger.info(
                        f"Exporting table {schema}.{table_str} -> {output_file}"
                    )

                select_query = self._build_chunked_query(
                    table=table_str,
                    schema=schema,
                    where_clause=where_clause,
                    custom_sql=custom_sql,
                    chunk_key=chunk_key,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                )

                header_sql = sql.SQL(", HEADER") if include_header else sql.SQL("")
                copy_command = sql.SQL(
                    "COPY ({}) TO STDOUT WITH (FORMAT csv, DELIMITER ','{header})",
                ).format(select_query, header=header_sql)

                with open(output_file, "w", encoding="utf-8") as f:
                    cursor.copy_expert(copy_command.as_string(client), f)

                count_query = sql.SQL("SELECT COUNT(*) FROM ({}) AS _cnt").format(
                    select_query,
                )
                cursor.execute(count_query)
                count_row = cursor.fetchone()
                row_count = (
                    int(count_row[0])
                    if count_row and count_row[0] is not None
                    else 0
                )
                result["total_rows"] += row_count
                result["exported_tables"].append(
                    {
                        "schema": schema,
                        "name": table_str,
                        "rows": row_count,
                        "file": output_file,
                    }
                )

                if logger:
                    logger.info(
                        "Table %s.%s exported successfully, rows: %s",
                        schema,
                        table_str,
                        row_count,
                    )
            except (OSError, psycopg2.Error) as exc:
                error_msg = (
                    f"Export failed for table {schema}.{table_str}: {str(exc)}"
                )
                if logger:
                    logger.error(error_msg)
                result["error_tables"].append(
                    {
                        "schema": schema,
                        "name": table_str,
                        "error": str(exc),
                    }
                )
                result["success"] = False
        except (OSError, psycopg2.Error) as exc:
            error_msg = f"Export process failed: {str(exc)}"
            if logger:
                logger.error(error_msg)
            result["success"] = False
            result["error"] = error_msg
        finally:
            if cursor is not None:
                cursor.close()

        return result

    def import_csv(
        self,
        client: psycopg2.extensions.connection,
        db_config: dict[str, Any],
        table_names: list[str],
        data_dir: str,
        schema: str = "public",
        pre_sql_file: str = "",
        need_backup: bool = False,
        truncate_before: bool = True,
        is_first_chunk: bool = False,
        logger: Any | None = None,
    ) -> dict[str, Any]:
        """Bulk-load CSVs for ``table_names`` with optional backup and pre-SQL.

        :param is_first_chunk: When ``True`` and ``truncate_before`` is also
            ``True``, truncate the target table before importing (first chunk
            of a migration). When ``False`` (default), skip truncation even if
            ``truncate_before`` is set, so subsequent chunks can append data.
        """
        schema = schema.strip() if isinstance(schema, str) else schema
        if not schema:
            schema = "public"

        result = {
            "success": True,
            "imported_tables": [],
            "error_tables": [],
            "backup_path": None,
            "data_directory": data_dir,
            "schema": schema,
        }

        if not table_names:
            result["success"] = False
            result["error"] = "No tables found to import"
            return result

        try:
            status = getattr(client, "status", psycopg2.extensions.STATUS_READY)
            if status != psycopg2.extensions.STATUS_READY:
                client.rollback()
            client.autocommit = False

            before_counts = self._get_table_counts(client, schema, table_names, logger)
            if logger:
                logger.info("Row counts before import:")
                for table, count in before_counts.items():
                    logger.info(f"  {table}: {count}")

            if need_backup:
                backup_dir = os.path.join(data_dir, "backup")
                result["backup_path"] = self._backup_tables(
                    client, schema, table_names, backup_dir, logger
                )

            if pre_sql_file:
                try:
                    pre_sql = read_sql_from_file(pre_sql_file)
                    self._execute_pre_sql(client, pre_sql, logger)
                    if logger:
                        logger.info("Pre-SQL executed successfully")
                except (OSError, UnicodeError, ValueError, psycopg2.Error) as exc:
                    error_msg = f"Pre-SQL execution failed: {str(exc)}"
                    if logger:
                        logger.error(error_msg)
                    result["error"] = error_msg
                    result["success"] = False
                    client.rollback()
                    return result

            copy_commands = generate_copy_commands(table_names, data_dir)

            imported_tables: list[str] = []
            for table, csv_file in copy_commands:
                try:
                    if logger:
                        logger.info(f"Importing {schema}.{table} <- {csv_file}")
                    with client.cursor() as cursor:
                        if truncate_before and is_first_chunk:
                            truncate_sql = sql.SQL("TRUNCATE TABLE {}.{}").format(
                                sql.Identifier(schema),
                                sql.Identifier(table),
                            )
                            cursor.execute(truncate_sql)
                            if logger:
                                logger.info(f"Table {schema}.{table} truncated")

                        with open(csv_file, encoding="utf-8") as f:
                            header_line = f.readline().strip()
                            columns = [
                                col.strip()
                                for col in header_line.split(",")
                                if col.strip()
                            ]
                            f.seek(0)

                            copy_sql = sql.SQL(
                                "COPY {}.{} ({}) FROM STDOUT WITH ("
                                "DELIMITER ',', FORMAT CSV, HEADER true, "
                                "ENCODING 'UTF8', QUOTE '\"', ESCAPE '\"')"
                            ).format(
                                sql.Identifier(schema),
                                sql.Identifier(table),
                                sql.SQL(", ").join(
                                    sql.Identifier(col) for col in columns
                                ),
                            )
                            if isinstance(client, psycopg2.extensions.connection):
                                copy_stmt = copy_sql.as_string(cursor)
                            else:
                                cols_join = ", ".join(
                                    _quote_pg_ident_segment(c) for c in columns
                                )
                                schema_tbl = (
                                    f"{_quote_pg_ident_segment(schema)}."
                                    f"{_quote_pg_ident_segment(table)}"
                                )
                                copy_stmt = (
                                    f"COPY {schema_tbl} ({cols_join}) FROM STDOUT "
                                    "WITH (DELIMITER ',', FORMAT CSV, HEADER true, "
                                    "ENCODING 'UTF8', QUOTE '\"', ESCAPE '\"')"
                                )
                            cursor.copy_expert(copy_stmt, f)

                    imported_tables.append(table)
                    if logger:
                        logger.info(f"Table {schema}.{table} imported successfully")
                except (OSError, psycopg2.Error, RuntimeError) as exc:
                    error_msg = f"Import failed for {schema}.{table}: {str(exc)}"
                    if logger:
                        logger.error(error_msg)
                    result["error_tables"].append({"table": table, "error": str(exc)})
                    result["success"] = False

            if result["success"]:
                client.commit()
                result["imported_tables"] = imported_tables
                if logger:
                    logger.info(
                        "All tables imported successfully, committing transaction"
                    )

                after_counts = self._get_table_counts(
                    client, schema, table_names, logger
                )
                if logger:
                    logger.info("Row counts after import:")
                    for table, count in after_counts.items():
                        before = before_counts.get(table, 0)
                        diff = count - before
                        if diff > 0:
                            change_str = f"+{diff} rows"
                        elif diff < 0:
                            change_str = f"{-diff} rows"
                        else:
                            change_str = "no change"
                        logger.info(f"  {table}: {count} ({change_str})")
            else:
                if logger:
                    logger.warning("Import encountered errors, transaction rolled back")
                client.rollback()
                result["imported_tables"] = []
        except (OSError, psycopg2.Error, RuntimeError, ValueError) as exc:
            error_msg = f"Import process failed: {str(exc)}"
            if logger:
                logger.error(error_msg)
            result["success"] = False
            result["error"] = error_msg
            result["imported_tables"] = []
            try:
                client.rollback()
            except psycopg2.Error:
                pass

        return result

    def copy_stream_transfer(
        self,
        src_client: psycopg2.extensions.connection,
        dst_client: psycopg2.extensions.connection,
        src_query: str,
        dst_table: str,
        columns: list[str],
        schema: str = "public",
    ) -> int:
        """PG to PG high-speed transfer via COPY through an in-memory buffer.

        Streams data from ``src_query`` on the source connection into the target
        table using ``COPY ... TO STDOUT`` followed by ``COPY ... FROM STDIN``,
        with an ``io.StringIO`` buffer as intermediary -- no disk I/O.

        :param src_client: Source PG connection.
        :param dst_client: Target PG connection.
        :param src_query: SELECT query to read data from the source.
        :param dst_table: Target table name.
        :param columns: Column names to insert into.
        :param schema: Target schema name (default ``"public"``).
        :returns: Number of rows transferred.
        """
        import csv
        import io

        buffer = io.StringIO()

        with src_client.cursor() as src_cur:
            copy_out = sql.SQL("COPY ({}) TO STDOUT WITH (FORMAT CSV, HEADER false)").format(
                sql.SQL(src_query),
            )
            if isinstance(src_client, psycopg2.extensions.connection):
                copy_out_str = copy_out.as_string(src_client)
            else:
                copy_out_str = (
                    f"COPY ({src_query}) TO STDOUT WITH (FORMAT CSV, HEADER false)"
                )
            src_cur.copy_expert(copy_out_str, buffer)

        content = buffer.getvalue()
        if not content.strip():
            return 0
        # Use csv.reader to count rows correctly even when fields contain newlines
        row_count = sum(1 for _ in csv.reader(io.StringIO(content)))

        buffer.seek(0)
        with dst_client.cursor() as dst_cur:
            cols_sql = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
            copy_in = sql.SQL("COPY {}.{} ({}) FROM STDIN WITH (FORMAT CSV)").format(
                sql.Identifier(schema),
                sql.Identifier(dst_table),
                cols_sql,
            )
            if isinstance(dst_client, psycopg2.extensions.connection):
                copy_in_str = copy_in.as_string(dst_client)
            else:
                cols_join = ", ".join(
                    _quote_pg_ident_segment(c) for c in columns
                )
                schema_tbl = (
                    f"{_quote_pg_ident_segment(schema)}."
                    f"{_quote_pg_ident_segment(dst_table)}"
                )
                copy_in_str = (
                    f"COPY {schema_tbl} ({cols_join}) "
                    f"FROM STDIN WITH (FORMAT CSV)"
                )
            dst_cur.copy_expert(copy_in_str, buffer)

        dst_client.commit()
        return row_count

    def export_sql(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Write schema data and DDL for ``schema`` into a single ``.sql`` file.

        :return: Summary dict with ``success``, ``export_file``, or ``error``.
        """
        client = kwargs.get("client")
        db_config = kwargs.get("db_config", {})
        export_dir = kwargs.get("export_dir")
        schema = kwargs.get("schema", "public")
        exclude_tables = kwargs.get("exclude_tables") or []
        include_truncate = kwargs.get("include_truncate", True)
        logger = kwargs.get("logger")

        if export_dir is None or not str(export_dir).strip():
            return {
                "success": False,
                "error": "export_dir is required",
                "schema": schema,
            }
        export_dir_str = str(export_dir)
        if client is None:
            return {
                "success": False,
                "error": "client is required",
                "schema": schema,
            }
        pg_client = client

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file = os.path.join(
            export_dir_str,
            f"{db_config.get('database', 'database')}_{schema}_{timestamp}.sql",
        )

        try:
            if hasattr(pg_client, "set_isolation_level"):
                try:
                    pg_client.set_isolation_level(
                        psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
                    )
                except psycopg2.Error:
                    pass

            with pg_client.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_type = 'BASE TABLE'
                    """,
                    (schema,),
                )
                tables = [row[0] for row in cursor.fetchall()]

                if exclude_tables:
                    tables = [t for t in tables if t not in exclude_tables]

                if not tables:
                    return {
                        "success": False,
                        "error": "No exportable tables found",
                        "schema": schema,
                    }

                os.makedirs(
                    os.path.dirname(os.path.abspath(export_file)), exist_ok=True
                )

                with open(export_file, "w", encoding="utf-8") as f:
                    f.write("-- Database export script\n")
                    f.write(f"-- Database: {db_config.get('database', '')}\n")
                    f.write(f"-- Schema: {schema}\n\n")
                    f.write(f"SET search_path TO {schema};\n\n")

                    for table in tables:
                        if logger:
                            logger.info(f"Exporting table {table}")

                        cursor.execute(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = %s AND table_name = %s
                            ORDER BY ordinal_position
                            """,
                            (schema, table),
                        )
                        column_names = [col[0] for col in cursor.fetchall()]

                        if include_truncate:
                            f.write(f"TRUNCATE TABLE {table} CASCADE;\n")

                        cursor.execute(f'SELECT * FROM "{schema}"."{table}"')
                        rows = cursor.fetchall()

                        if rows:
                            for row in rows:
                                values = []
                                for value in row:
                                    if value is None:
                                        values.append("NULL")
                                    elif isinstance(value, bool):
                                        values.append("true" if value else "false")
                                    elif isinstance(value, (int, float)):
                                        values.append(str(value))
                                    else:
                                        value_str = str(value).replace("'", "''")
                                        values.append(f"'{value_str}'")

                                columns_str = '", "'.join(column_names)
                                values_str = ", ".join(values)
                                line = (
                                    f'INSERT INTO "{table}" ("{columns_str}") '
                                    f"VALUES ({values_str});\n"
                                )
                                f.write(line)

                        f.write("\n")

            if logger:
                logger.info("Database export completed")
            return {"success": True, "schema": schema, "export_file": export_file}
        except (OSError, psycopg2.Error, RuntimeError, ValueError) as exc:
            if logger:
                logger.error(f"Export failed: {str(exc)}")
            return {"success": False, "error": str(exc), "schema": schema}
