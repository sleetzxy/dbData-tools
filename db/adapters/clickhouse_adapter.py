from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.importer_csv import generate_copy_commands, read_sql_from_file


class ClickHouseAdapter:
    db_type = "clickhouse"

    @classmethod
    def _validate_identifier(cls, name: str, label: str) -> str:
        cleaned = name.strip()
        if not cleaned or "\x00" in cleaned:
            raise ValueError(f"Invalid {label} identifier: {name}")
        return cleaned

    @staticmethod
    def _quote_identifier(name: str) -> str:
        return f"`{name.replace('`', '``')}`"

    def create_client(self, db_config: Dict[str, Any]) -> Any:
        import clickhouse_connect

        return clickhouse_connect.get_client(
            host=db_config["host"],
            port=db_config["port"],
            username=db_config["user"],
            password=db_config["password"],
            database=db_config["database"],
        )

    def close_client(self, client: Any) -> None:
        if hasattr(client, "close"):
            client.close()
            return
        if hasattr(client, "disconnect"):
            client.disconnect()

    def _backup_tables(
        self,
        client: Any,
        database: str,
        table_names: List[str],
        backup_dir: str,
        logger: Optional[Any] = None,
    ) -> str:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = os.path.join(backup_dir, timestamp)
        os.makedirs(backup_path, exist_ok=True)

        for table in table_names:
            table_name = self._validate_identifier(str(table).strip(), "table")
            qualified = f"{self._quote_identifier(database)}.{self._quote_identifier(table_name)}"
            backup_file = os.path.join(backup_path, f"{table_name}.csv")
            query = f"SELECT * FROM {qualified} FORMAT CSVWithNames"

            if logger:
                logger.info(f"\u6b63\u5728\u5907\u4efd\u8868 {database}.{table_name} -> {backup_file}")

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
                data = response if isinstance(response, bytes) else str(response).encode("utf-8")
                with open(backup_file, "wb") as f:
                    f.write(data)
            else:
                raise RuntimeError("ClickHouse client does not support raw backup query")

        return backup_path

    def export_csv(
        self,
        client: Any,
        db_config: Dict[str, Any],
        tables: List[str],
        export_dir: str,
        schema: str = "",
        include_header: bool = True,
        logger: Optional[Any] = None,
    ) -> Dict[str, Any]:
        database = self._validate_identifier(str(db_config.get("database", "")).strip(), "database")
        result = {
            "success": True,
            "exported_tables": [],
            "error_tables": [],
            "total_rows": 0,
            "schema": "",
        }

        os.makedirs(export_dir, exist_ok=True)

        for table in tables:
            try:
                table_name = self._validate_identifier(str(table).strip(), "table")
                output_file = os.path.join(export_dir, f"{table_name}.csv")
                if logger:
                    logger.info(f"Exporting table {database}.{table_name} -> {output_file}")

                format_name = "CSVWithNames" if include_header else "CSV"
                qualified = f"{self._quote_identifier(database)}.{self._quote_identifier(table_name)}"
                query = f"SELECT * FROM {qualified} FORMAT {format_name}"

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
                    count_result = client.query(f"SELECT count() FROM {qualified}")
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
                    logger.info(f"Export finished for {database}.{table_name}, rows: {row_count}")
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
        db_config: Dict[str, Any],
        table_names: List[str],
        data_dir: str,
        schema: str = "",
        pre_sql_file: str = "",
        need_backup: bool = False,
        logger: Optional[Any] = None,
    ) -> Dict[str, Any]:
        database = self._validate_identifier(str(db_config.get("database", "")).strip(), "database")
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
                        logger.info(f"\u6267\u884c\u9884\u5904\u7406 SQL: {statement[:100]}")
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
                qualified = f"{self._quote_identifier(database)}.{self._quote_identifier(table_name)}"
                if logger:
                    logger.info(f"\u6b63\u5728\u5bfc\u5165 {database}.{table_name} <- {csv_file}")
                if hasattr(client, "command"):
                    client.command(f"TRUNCATE TABLE {qualified}")
                    with open(csv_file, "rb") as f:
                        data = f.read()
                        client.command(
                            f"INSERT INTO {qualified} FORMAT CSVWithNames",
                            data=data,
                        )
                else:
                    raise RuntimeError("ClickHouse client does not support command()")

                result["imported_tables"].append(table_name)
                if logger:
                    logger.info(f"\u8868 {database}.{table_name} \u5bfc\u5165\u5b8c\u6210")
            except Exception as exc:
                error_msg = f"\u5bfc\u5165 {database}.{table} \u5931\u8d25: {exc}"
                if logger:
                    logger.error(error_msg)
                result["error_tables"].append({"table": table, "error": str(exc)})
                result["success"] = False

        return result

    @staticmethod
    def _split_sql_statements(sql_text: str) -> List[str]:
        statements: List[str] = []
        buffer: List[str] = []
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

    def export_sql(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        client = kwargs.get("client")
        db_config = kwargs.get("db_config", {})
        export_dir = kwargs.get("export_dir")
        exclude_tables = kwargs.get("exclude_tables") or []
        include_truncate = kwargs.get("include_truncate", True)
        logger = kwargs.get("logger")

        database = self._validate_identifier(str(db_config.get("database", "")).strip(), "database")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file = os.path.join(export_dir, f"{database}_{timestamp}.sql")

        def _extract_rows(result: Any) -> Sequence[Tuple[Any, ...]]:
            if hasattr(result, "result_rows"):
                return result.result_rows
            if hasattr(result, "result_set"):
                return result.result_set
            if isinstance(result, list):
                return result
            return []

        def _query(statement: str) -> Sequence[Tuple[Any, ...]]:
            if hasattr(client, "query"):
                return _extract_rows(client.query(statement))
            if hasattr(client, "raw_query"):
                response = client.raw_query(statement)
                if isinstance(response, (list, tuple)):
                    return response
                return []
            raise RuntimeError("ClickHouse client does not support query")

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
                return {"success": False, "error": "No exportable tables found", "schema": ""}

            os.makedirs(os.path.dirname(os.path.abspath(export_file)), exist_ok=True)

            with open(export_file, "w", encoding="utf-8") as f:
                f.write("-- ClickHouse SQL export\n")
                f.write(f"-- database: {database}\n\n")

                for table in tables:
                    table_name = self._validate_identifier(table, "table")
                    qualified = f"{self._quote_identifier(database)}.{self._quote_identifier(table_name)}"

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

                    if hasattr(client, "query"):
                        data_result = client.query(f"SELECT * FROM {qualified}")
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
                        columns_str = ", ".join(self._quote_identifier(name) for name in column_names)
                        for row in rows:
                            values_str = ", ".join(_serialize_value(value) for value in row)
                            f.write(
                                f"INSERT INTO {qualified} ({columns_str}) VALUES ({values_str});\n"
                            )

                    f.write("\n")

            return {"success": True, "schema": "", "export_file": export_file}
        except Exception as exc:
            if logger:
                logger.error(f"Export failed: {exc}")
            return {"success": False, "error": str(exc), "schema": ""}
