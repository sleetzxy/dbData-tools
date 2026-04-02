from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2 import sql

from core.importer_csv import generate_copy_commands, read_sql_from_file


class PostgreSQLAdapter:
    db_type = "postgresql"

    def create_client(self, db_config: Dict[str, Any]) -> psycopg2.extensions.connection:
        return psycopg2.connect(
            host=db_config["host"],
            port=db_config["port"],
            user=db_config["user"],
            password=db_config["password"],
            database=db_config["database"],
        )

    def close_client(self, client: psycopg2.extensions.connection) -> None:
        client.close()

    @staticmethod
    def _get_table_counts(
        client: psycopg2.extensions.connection,
        schema: str,
        table_names: List[str],
        logger: Optional[Any] = None,
    ) -> Dict[str, int]:
        if not table_names:
            return {}

        try:
            with client.cursor() as cursor:
                counts: Dict[str, int] = {}
                for table in table_names:
                    count_query = sql.SQL("SELECT COUNT(1) FROM {}.{}").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                    )
                    cursor.execute(count_query)
                    row = cursor.fetchone()
                    counts[table] = row[0] if row else 0
                return counts
        except Exception as exc:
            if logger:
                logger.error(f"Failed to get row counts: {exc}")
            return {}

    @staticmethod
    def _backup_tables(
        client: psycopg2.extensions.connection,
        schema: str,
        table_names: List[str],
        backup_dir: str,
        logger: Optional[Any] = None,
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
                            "COPY (SELECT * FROM {}.{}) TO STDOUT WITH (FORMAT CSV, HEADER true, DELIMITER ',', ENCODING 'UTF8')"
                        ).format(
                            sql.Identifier(schema),
                            sql.Identifier(table),
                        )
                        cursor.copy_expert(backup_sql.as_string(client), f)
                    if logger:
                        logger.info(f"Table {table} backup completed -> {backup_file}")
                except Exception as exc:
                    if logger:
                        logger.error(f"Table {table} backup failed: {exc}")

        return backup_path

    @staticmethod
    def _execute_pre_sql(
        client: psycopg2.extensions.connection,
        pre_sql: str,
        logger: Optional[Any] = None,
    ) -> None:
        if not pre_sql.strip():
            if logger:
                logger.info("No pre-SQL provided")
            return

        if logger:
            logger.info("Starting pre-SQL execution")

        def split_sql_statements(sql_text: str) -> List[str]:
            statements: List[str] = []
            buffer: List[str] = []
            i = 0
            in_single = False
            in_double = False
            in_line_comment = False
            in_block_comment = False
            dollar_tag: Optional[str] = None

            def _match_dollar_tag(text: str, start: int) -> Optional[str]:
                if text[start] != "$":
                    return None
                end = text.find("$", start + 1)
                if end == -1:
                    return None
                tag = text[start:end + 1]
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

            return [stmt for stmt in statements if stmt and not stmt.strip().upper().startswith("DELIMITER ")]

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
                        sql_statement[:100] + "..." if len(sql_statement) > 100 else sql_statement
                    )
                    if logger:
                        logger.info(
                            f"Executing SQL statement {i}/{len(sql_statements)}: {sql_preview}"
                        )

                    cursor.execute(sql_statement)

                    affected = cursor.rowcount
                    if logger:
                        if affected >= 0:
                            logger.info(f"SQL executed successfully, affected rows: {affected}")
                        else:
                            logger.info("DDL executed successfully")
                except Exception as exc:
                    if logger:
                        logger.error(
                            f"SQL execution failed - statement {i}: {sql_statement[:200]}..."
                        )
                        logger.error(f"Error details: {str(exc)}")

                    error_str = str(exc).lower()
                    if any(keyword in error_str for keyword in ["already exists", "duplicate", "exists"]):
                        if logger:
                            logger.warning("Object already exists, skipped current SQL")
                        continue
                    raise

    def export_csv(
        self,
        client: psycopg2.extensions.connection,
        db_config: Dict[str, Any],
        tables: List[str],
        export_dir: str,
        schema: str = "public",
        include_header: bool = True,
        logger: Optional[Any] = None,
    ) -> Dict[str, Any]:
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
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
                (schema,),
            )
            if not cursor.fetchone():
                result["success"] = False
                result["error"] = f"Schema '{schema}' does not exist"
                return result

            for table in tables:
                try:
                    output_file = os.path.join(export_dir, f"{table}.csv")
                    if logger:
                        logger.info(f"Exporting table {schema}.{table} -> {output_file}")

                    header_sql = sql.SQL(", HEADER") if include_header else sql.SQL("")
                    copy_command = sql.SQL(
                        "COPY {}.{} TO STDOUT WITH (FORMAT csv, DELIMITER ','{header})"
                    ).format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        header=header_sql,
                    )

                    with open(output_file, "w", encoding="utf-8") as f:
                        cursor.copy_expert(copy_command.as_string(client), f)

                    count_query = sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                    )
                    cursor.execute(count_query)
                    row_count = cursor.fetchone()[0]
                    result["total_rows"] += row_count
                    result["exported_tables"].append(
                        {
                            "schema": schema,
                            "name": table,
                            "rows": row_count,
                            "file": output_file,
                        }
                    )

                    if logger:
                        logger.info(
                            f"Table {schema}.{table} exported successfully, rows: {row_count}"
                        )
                except Exception as exc:
                    error_msg = f"Export failed for table {schema}.{table}: {str(exc)}"
                    if logger:
                        logger.error(error_msg)
                    result["error_tables"].append(
                        {
                            "schema": schema,
                            "name": table,
                            "error": str(exc),
                        }
                    )
                    result["success"] = False
        except Exception as exc:
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
        db_config: Dict[str, Any],
        table_names: List[str],
        data_dir: str,
        schema: str = "public",
        pre_sql_file: str = "",
        need_backup: bool = False,
        truncate_before: bool = True,
        logger: Optional[Any] = None,
    ) -> Dict[str, Any]:
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
            client.autocommit = False

            before_counts = self._get_table_counts(client, schema, table_names, logger)
            if logger:
                logger.info("Row counts before import:")
                for table, count in before_counts.items():
                    logger.info(f"  {table}: {count}")

            if need_backup:
                backup_dir = os.path.join(data_dir, "backup")
                result["backup_path"] = self._backup_tables(client, schema, table_names, backup_dir, logger)

            if pre_sql_file:
                try:
                    pre_sql = read_sql_from_file(pre_sql_file)
                    self._execute_pre_sql(client, pre_sql, logger)
                    if logger:
                        logger.info("Pre-SQL executed successfully")
                except Exception as exc:
                    error_msg = f"Pre-SQL execution failed: {str(exc)}"
                    if logger:
                        logger.error(error_msg)
                    result["error"] = error_msg
                    result["success"] = False
                    client.rollback()
                    return result

            copy_commands = generate_copy_commands(table_names, data_dir)

            imported_tables: List[str] = []
            for table, csv_file in copy_commands:
                try:
                    if logger:
                        logger.info(f"Importing {schema}.{table} <- {csv_file}")
                    with client.cursor() as cursor:
                        if truncate_before:
                            truncate_sql = sql.SQL("TRUNCATE TABLE {}.{}").format(
                                sql.Identifier(schema),
                                sql.Identifier(table),
                            )
                            cursor.execute(truncate_sql)
                            if logger:
                                logger.info(f"Table {schema}.{table} truncated")

                        with open(csv_file, "r", encoding="utf-8") as f:
                            header_line = f.readline().strip()
                            columns = [col.strip() for col in header_line.split(',') if col.strip()]
                            f.seek(0)

                            copy_sql = sql.SQL(
                                "COPY {}.{} ({}) FROM STDOUT WITH (DELIMITER ',', FORMAT CSV, HEADER true, ENCODING 'UTF8', QUOTE '\"', ESCAPE '\"')"
                            ).format(
                                sql.Identifier(schema),
                                sql.Identifier(table),
                                sql.SQL(", ").join(sql.Identifier(col) for col in columns),
                            )
                            cursor.copy_expert(copy_sql.as_string(client), f)

                    imported_tables.append(table)
                    if logger:
                        logger.info(f"Table {schema}.{table} imported successfully")
                except Exception as exc:
                    error_msg = f"Import failed for {schema}.{table}: {str(exc)}"
                    if logger:
                        logger.error(error_msg)
                    result["error_tables"].append({"table": table, "error": str(exc)})
                    result["success"] = False

            if result["success"]:
                client.commit()
                result["imported_tables"] = imported_tables
                if logger:
                    logger.info("All tables imported successfully, committing transaction")

                after_counts = self._get_table_counts(client, schema, table_names, logger)
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
        except Exception as exc:
            error_msg = f"Import process failed: {str(exc)}"
            if logger:
                logger.error(error_msg)
            result["success"] = False
            result["error"] = error_msg
            result["imported_tables"] = []
            try:
                client.rollback()
            except Exception:
                pass

        return result

    def export_sql(self, *args: Any, **kwargs: Any) -> None:
        client = kwargs.get("client")
        db_config = kwargs.get("db_config", {})
        export_dir = kwargs.get("export_dir")
        schema = kwargs.get("schema", "public")
        exclude_tables = kwargs.get("exclude_tables") or []
        include_truncate = kwargs.get("include_truncate", True)
        logger = kwargs.get("logger")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file = os.path.join(
            export_dir,
            f"{db_config.get('database', 'database')}_{schema}_{timestamp}.sql",
        )

        try:
            if hasattr(client, "set_isolation_level"):
                try:
                    client.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                except Exception:
                    pass

            with client.cursor() as cursor:
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
                    return {"success": False, "error": "No exportable tables found", "schema": schema}

                os.makedirs(os.path.dirname(os.path.abspath(export_file)), exist_ok=True)

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
                                f.write(
                                    f'INSERT INTO "{table}" ("{columns_str}") VALUES ({values_str});\n'
                                )

                        f.write("\n")

            if logger:
                logger.info("Database export completed")
            return {"success": True, "schema": schema, "export_file": export_file}
        except Exception as exc:
            if logger:
                logger.error(f"Export failed: {str(exc)}")
            return {"success": False, "error": str(exc), "schema": schema}
