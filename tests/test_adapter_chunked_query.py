"""Tests for _build_chunked_query on PostgreSQL and ClickHouse adapters.

Covers all 4 query priorities for each adapter:
  1. custom_sql + chunk
  2. where_clause + chunk
  3. chunk only
  4. neither (full table)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg2 import sql as psql

from db.adapters.clickhouse_adapter import ClickHouseAdapter
from db.adapters.postgresql_adapter import PostgreSQLAdapter

# ---------------------------------------------------------------------------
# Helper: render psycopg2.sql.Composed → plain SQL string
# ---------------------------------------------------------------------------


def _render_pg_query(query: psql.Composed) -> str:
    """Walk a ``psycopg2.sql.Composed`` object and produce a SQL string.

    This avoids needing a live PG connection just for testing query structure.
    """
    parts: list[str] = []
    for part in query:
        if isinstance(part, psql.Composed):
            parts.append(_render_pg_query(part))
        elif isinstance(part, psql.SQL):
            parts.append(part.string)
        elif isinstance(part, psql.Identifier):
            parts.append('"' + part.string.replace('"', '""') + '"')
        elif isinstance(part, psql.Literal):
            v: Any = part.wrapped
            if v is None:
                parts.append("NULL")
            elif isinstance(v, bool):
                parts.append("true" if v else "false")
            elif isinstance(v, (int, float)):
                parts.append(str(v))
            elif isinstance(v, str):
                escaped = v.replace("'", "''")
                parts.append(f"'{escaped}'")
            elif isinstance(v, datetime):
                parts.append(f"'{v.isoformat()}'")
            else:
                parts.append(str(v))
        else:
            parts.append(str(part))
    return "".join(parts)


# ===================================================================
# PostgreSQLAdapter
# ===================================================================


class TestPostgreSQLChunkedQuery:
    """All 4 priorities for PostgreSQL _build_chunked_query."""

    adapter = PostgreSQLAdapter  # static method, no instance needed

    def test_pg_priority1_custom_sql_with_chunk(self) -> None:
        """custom_sql + chunk: wrap as subquery + WHERE + ORDER BY."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="public",
            custom_sql="SELECT * FROM users WHERE active = true",
            chunk_key="id",
            chunk_start=0,
            chunk_end=100,
        )
        sql_str = _render_pg_query(query)
        assert (
            'SELECT * FROM (SELECT * FROM users WHERE active = true) AS _sub'
            in sql_str
        )
        assert '"id" >= 0' in sql_str
        assert '"id" < 100' in sql_str
        assert 'ORDER BY "id"' in sql_str

    def test_pg_priority1_custom_sql_without_chunk(self) -> None:
        """custom_sql without chunk: plain subquery, no WHERE/ORDER BY."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="public",
            custom_sql="SELECT * FROM users WHERE active = true",
        )
        sql_str = _render_pg_query(query)
        assert (
            'SELECT * FROM (SELECT * FROM users WHERE active = true) AS _sub'
            == sql_str
        )

    def test_pg_priority2_where_clause_with_chunk(self) -> None:
        """where_clause + chunk: WHERE with chunk conditions AND user clause."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="public",
            where_clause="status = 'active'",
            chunk_key="id",
            chunk_start=0,
            chunk_end=100,
        )
        sql_str = _render_pg_query(query)
        assert 'SELECT * FROM "public"."users"' in sql_str
        assert '"id" >= 0' in sql_str
        assert '"id" < 100' in sql_str
        assert "(status = 'active')" in sql_str
        assert 'ORDER BY "id"' in sql_str

    def test_pg_priority3_chunk_only(self) -> None:
        """chunk only: WHERE with chunk conditions + ORDER BY."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="public",
            chunk_key="id",
            chunk_start=0,
            chunk_end=100,
        )
        sql_str = _render_pg_query(query)
        assert 'SELECT * FROM "public"."users"' in sql_str
        assert '"id" >= 0' in sql_str
        assert '"id" < 100' in sql_str
        assert 'ORDER BY "id"' in sql_str
        assert "status" not in sql_str.lower()

    def test_pg_priority3_chunk_no_upper_bound(self) -> None:
        """Chunk with only key_start (keyset pagination)."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="public",
            chunk_key="id",
            chunk_start=100,
        )
        sql_str = _render_pg_query(query)
        assert '"id" >= 100' in sql_str
        assert '"id" <' not in sql_str  # no upper bound
        assert 'ORDER BY "id"' in sql_str

    def test_pg_priority4_neither(self) -> None:
        """No custom_sql, no where_clause, no chunk: SELECT * FROM schema.table."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="public",
        )
        sql_str = _render_pg_query(query)
        assert sql_str == 'SELECT * FROM "public"."users"'

    def test_pg_identifier_quoting(self) -> None:
        """Identifiers are properly double-quoted."""
        query = self.adapter._build_chunked_query(
            table="order details",
            schema="my schema",
        )
        sql_str = _render_pg_query(query)
        assert '"my schema"' in sql_str
        assert '"order details"' in sql_str

    def test_pg_literal_quoting(self) -> None:
        """String literals in chunk bounds are properly escaped."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="public",
            chunk_key="name",
            chunk_start="O'Brien",
        )
        sql_str = _render_pg_query(query)
        assert '"name" >= \'O\'\'Brien\'' in sql_str


# ===================================================================
# ClickHouseAdapter
# ===================================================================


class TestClickHouseChunkedQuery:
    """All 4 priorities for ClickHouse _build_chunked_query."""

    def setup_method(self) -> None:
        self.adapter = ClickHouseAdapter()

    def test_ch_priority1_custom_sql_with_chunk(self) -> None:
        """custom_sql + chunk: subquery + WHERE + ORDER BY."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="default",
            custom_sql="SELECT * FROM default.users WHERE active = 1",
            chunk_key="id",
            chunk_start=0,
            chunk_end=100,
        )
        expected_sub = (
            "SELECT * FROM (SELECT * FROM default.users WHERE active = 1) AS _sub"
        )
        assert expected_sub in query
        assert "`id` >= 0" in query
        assert "`id` < 100" in query
        assert "ORDER BY `id`" in query

    def test_ch_priority1_custom_sql_without_chunk(self) -> None:
        """custom_sql without chunk: plain subquery."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="default",
            custom_sql="SELECT * FROM default.users",
        )
        assert query == "SELECT * FROM (SELECT * FROM default.users) AS _sub"

    def test_ch_priority2_where_clause_with_chunk(self) -> None:
        """where_clause + chunk."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="default",
            where_clause="status = 'active'",
            chunk_key="id",
            chunk_start=0,
            chunk_end=100,
        )
        assert "SELECT * FROM `default`.`users`" in query
        assert "`id` >= 0" in query
        assert "`id` < 100" in query
        assert "(status = 'active')" in query
        assert "ORDER BY `id`" in query

    def test_ch_priority3_chunk_only(self) -> None:
        """chunk only: WHERE + ORDER BY."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="default",
            chunk_key="id",
            chunk_start=0,
            chunk_end=100,
        )
        assert "SELECT * FROM `default`.`users`" in query
        assert "`id` >= 0" in query
        assert "`id` < 100" in query
        assert "ORDER BY `id`" in query

    def test_ch_priority3_chunk_no_upper_bound(self) -> None:
        """Chunk with only key_start (keyset pagination)."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="default",
            chunk_key="id",
            chunk_start=100,
        )
        assert "`id` >= 100" in query
        assert "`id` <" not in query
        assert "ORDER BY `id`" in query

    def test_ch_priority4_neither(self) -> None:
        """No custom_sql, no where, no chunk: SELECT * FROM db.table."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="default",
        )
        assert query == "SELECT * FROM `default`.`users`"

    def test_ch_bare_table_no_schema(self) -> None:
        """When schema is empty, only the table name is used (no database prefix)."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="",
        )
        assert query == "SELECT * FROM ``.`users`"  # empty backtick pair for empty db

    def test_ch_literal_quoting(self) -> None:
        """String chunk bounds are single-quoted with proper escaping."""
        query = self.adapter._build_chunked_query(
            table="users",
            schema="default",
            chunk_key="name",
            chunk_start="O'Brien",
        )
        assert "`name` >= 'O''Brien'" in query

    def test_ch_datetime_literal(self) -> None:
        """Datetime chunk bounds are formatted via isoformat()."""
        dt = datetime(2024, 6, 15, 10, 30, 0)
        query = self.adapter._build_chunked_query(
            table="events",
            schema="default",
            chunk_key="ts",
            chunk_start=dt,
        )
        assert "`ts` >= '2024-06-15T10:30:00'" in query
