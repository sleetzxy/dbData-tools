"""分块策略模块：自动检测分块键、探测值域范围、生成 ChunkSpec。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from core.migration.models import ChunkSpec, MigrationCondition


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def detect_chunk_key(
    adapter: Any,
    client: Any,
    table: str,
    schema: str = "",
) -> str:
    """自动检测表的主键列作为分块键。

    **PostgreSQL**
        查询 ``information_schema.table_constraints`` +
        ``information_schema.key_column_usage`` 获取主键首列。

    **ClickHouse**
        查询 ``system.columns`` 中 ``is_in_primary_key = 1`` 的首列。

    :param adapter: 数据库适配器实例（含 ``db_type`` 属性）。
    :param client: 数据库连接／客户端实例。
    :param table: 表名。
    :param schema: PG 模式名或 CH 数据库名。PG 空值时默认 ``"public"``。
    :return: 首列主键字段名。
    :raises ValueError: 未找到主键时抛出。
    """
    db_type = adapter.db_type

    if db_type == "postgresql":
        return _detect_pg_pk(client, table, schema or "public")
    if db_type == "clickhouse":
        return _detect_ch_pk(client, table, schema)

    raise ValueError(f"不支持的数据库类型: {db_type}")


def probe_range(
    adapter: Any,
    client: Any,
    table: str,
    chunk_key: str,
    schema: str = "",
) -> tuple[Any, Any]:
    """查询分块键列的最小值与最大值。

    :param adapter: 数据库适配器实例。
    :param client: 数据库连接／客户端实例。
    :param table: 表名。
    :param chunk_key: 分块键列名。
    :param schema: PG 模式名或 CH 数据库名。
    :return: ``(min_val, max_val)`` 元组。表为空时两个值均为 ``None``。
    """
    db_type = adapter.db_type

    if db_type == "postgresql":
        return _probe_pg_range(client, table, chunk_key, schema or "public")
    if db_type == "clickhouse":
        return _probe_ch_range(client, table, chunk_key, schema)

    raise ValueError(f"不支持的数据库类型: {db_type}")


def compute_chunks(
    adapter: Any,
    client: Any,
    table: str,
    cond: MigrationCondition,
    schema: str = "",
) -> list[ChunkSpec]:
    """根据迁移条件计算表的分块列表。

    流程
        1. 确定分块键（优先 ``cond.chunk_key``，否则自动检测）。
        2. 探测值域范围 ``[min, max]``。
        3. 空表 → 返回一个无边界的分块。
        4. 根据键类型拆分为实际分块：

           - **整型** — 等值区间，半开区间 ``[start, end)``，末块覆盖 ``max``。
           - **日期时间** — 等时间跨度，半开区间，末块 ``key_end = None``。
           - **字符串/UUID** — 返回指示起始值的单分块，编排器负责 keyset
             pagination。

    :param adapter: 数据库适配器实例。
    :param client: 数据库连接／客户端实例。
    :param table: 表名。
    :param cond: 迁移条件（含分块配置）。
    :param schema: PG 模式名或 CH 数据库名。
    :return: ``ChunkSpec`` 列表。
    """
    chunk_key = cond.chunk_key or detect_chunk_key(
        adapter, client, table, schema,
    )
    min_val, max_val = probe_range(
        adapter, client, table, chunk_key, schema,
    )

    # 空表
    if min_val is None or max_val is None:
        return [ChunkSpec(chunk_index=0, key_start=None, key_end=None)]

    key_type = _classify_key_type(min_val)

    if key_type == "int":
        return _compute_int_chunks(int(min_val), int(max_val), cond.chunk_size)
    if key_type == "datetime":
        return _compute_datetime_chunks(min_val, max_val, cond.chunk_size)
    # str / uuid → 返回起始值，编排器执行 keyset pagination
    return [ChunkSpec(chunk_index=0, key_start=min_val, key_end=None)]


# ---------------------------------------------------------------------------
# 类型分类
# ---------------------------------------------------------------------------


def _classify_key_type(val: Any) -> str:
    """根据样本值判断分块键类型。

    :param val: 分块键列的样本值（通常是 MIN 值）。
    :return: ``"int"`` | ``"datetime"`` | ``"str"``。
    """
    if val is None:
        return "str"
    if isinstance(val, bool):
        return "str"
    if isinstance(val, int):
        return "int"
    if isinstance(val, datetime):
        return "datetime"
    # 兼容 numpy / pandas 等数值类型
    if hasattr(val, "__int__") and not isinstance(val, (str, bytes)):
        return "int"
    return "str"


# ---------------------------------------------------------------------------
# PostgreSQL 内部实现
# ---------------------------------------------------------------------------


def _detect_pg_pk(
    client: Any,
    table: str,
    schema: str,
) -> str:
    """通过 information_schema 查询 PG 表主键首列。"""
    with client.cursor() as cur:
        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = %s
                AND tc.table_name = %s
            ORDER BY kcu.ordinal_position
            """,
            (schema, table),
        )
        row = cur.fetchone()
        if row:
            return str(row[0])
        raise ValueError(
            f"表 {schema}.{table} 未找到主键，请手动指定 chunk_key",
        )


def _probe_pg_range(
    client: Any,
    table: str,
    chunk_key: str,
    schema: str,
) -> tuple[Any, Any]:
    """查询 PG 表分块键列的 MIN/MAX。"""
    cur = client.cursor()
    try:
        from psycopg2 import sql as psql

        query = psql.SQL(
            "SELECT MIN({key}), MAX({key}) FROM {schema}.{table}",
        ).format(
            key=psql.Identifier(chunk_key),
            schema=psql.Identifier(schema),
            table=psql.Identifier(table),
        )
        cur.execute(query)
        row = cur.fetchone()
        if row is None or row[0] is None:
            return (None, None)
        return (row[0], row[1])
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# ClickHouse 内部实现
# ---------------------------------------------------------------------------


def _quote_ch(name: str) -> str:
    """反引号包裹 CH 标识符并转义内部反引号。"""
    return f"`{name.replace('`', '``')}`"


def _extract_ch_rows(result: Any) -> list[tuple]:
    """从 ClickHouse 查询结果中提取行列表。"""
    if hasattr(result, "result_rows"):
        return list(result.result_rows)
    if hasattr(result, "result_set"):
        return list(result.result_set)
    if isinstance(result, (list, tuple)):
        return list(result)
    return []


def _detect_ch_pk(
    client: Any,
    table: str,
    database: str,
) -> str:
    """通过 system.columns 查询 CH 表主键首列。"""
    safe_db = database.replace("'", "''")
    safe_tbl = table.replace("'", "''")
    result = client.query(
        "SELECT name FROM system.columns "
        "WHERE database = %(database)s AND table = %(table)s "
        "AND is_in_primary_key = 1 ORDER BY position",
        parameters={"database": database, "table": table},
    )
    rows = _extract_ch_rows(result)
    if rows:
        return str(rows[0][0])
    raise ValueError(
        f"表 {safe_db}.{safe_tbl} 未找到主键，请手动指定 chunk_key",
    )


def _probe_ch_range(
    client: Any,
    table: str,
    chunk_key: str,
    database: str,
) -> tuple[Any, Any]:
    """查询 CH 表分块键列的 MIN/MAX。"""
    key_col = _quote_ch(chunk_key)
    if database:
        qualified = f"{_quote_ch(database)}.{_quote_ch(table)}"
    else:
        qualified = _quote_ch(table)

    result = client.query(
        f"SELECT min({key_col}), max({key_col}) FROM {qualified}",
    )
    rows = _extract_ch_rows(result)
    if not rows or rows[0][0] is None:
        return (None, None)
    return (rows[0][0], rows[0][1])


# ---------------------------------------------------------------------------
# 分块拆分算法
# ---------------------------------------------------------------------------


def _compute_int_chunks(
    min_val: int,
    max_val: int,
    chunk_size: int,
) -> list[ChunkSpec]:
    """将整型键范围拆分为等值区间的分块。

    分块语义为半开区间 ``[key_start, key_end)``；末块 ``key_end = max_val + 1``
    以确保覆盖 ``max_val``。

    :param min_val: 最小值（含）。
    :param max_val: 最大值（含）。
    :param chunk_size: 每分块期望包含的取值个数。
    """
    span = max_val - min_val + 1
    num_chunks = max(1, math.ceil(span / chunk_size))
    actual_size = math.ceil(span / num_chunks)

    chunks: list[ChunkSpec] = []
    for i in range(num_chunks):
        start = min_val + i * actual_size
        if i < num_chunks - 1:
            end = min_val + (i + 1) * actual_size
        else:
            end = max_val + 1
        chunks.append(ChunkSpec(chunk_index=i, key_start=start, key_end=end))
    return chunks


def _compute_datetime_chunks(
    min_val: datetime,
    max_val: datetime,
    chunk_size: int,
) -> list[ChunkSpec]:
    """将日期时间键范围拆分为等时间长度的分块。

    分块语义为半开区间 ``[key_start, key_end)``；末块 ``key_end = None``
    （无上界）。

    :param min_val: 最小值（含）。
    :param max_val: 最大值（含）。
    :param chunk_size: 每分块期望覆盖的秒数。
    """
    min_ts = min_val.timestamp()
    max_ts = max_val.timestamp()
    total_seconds = max_ts - min_ts

    if total_seconds <= 0:
        return [ChunkSpec(chunk_index=0, key_start=min_val, key_end=min_val)]

    num_chunks = max(1, math.ceil(total_seconds / chunk_size))
    seconds_per_chunk = total_seconds / num_chunks

    chunks: list[ChunkSpec] = []
    for i in range(num_chunks):
        start = datetime.fromtimestamp(min_ts + i * seconds_per_chunk)
        if i < num_chunks - 1:
            end = datetime.fromtimestamp(
                min_ts + (i + 1) * seconds_per_chunk,
            )
        else:
            end = None  # 无上界，编排器自行处理
        chunks.append(ChunkSpec(chunk_index=i, key_start=start, key_end=end))
    return chunks
