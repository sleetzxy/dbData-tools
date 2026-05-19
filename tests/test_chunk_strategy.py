"""Tests for chunk strategy: key classification, int and dt chunking."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pytest

from core.migration.chunk_strategy import (
    _classify_key_type,
    _compute_datetime_chunks,
    _compute_int_chunks,
    compute_chunks,
    detect_chunk_key,
    probe_range,
)
from core.migration.models import MigrationCondition

# ---------------------------------------------------------------------------
# _classify_key_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("val, expected", [
    (42, "int"),
    (0, "int"),
    (-1, "int"),
    (999999999999, "int"),
])
def test_classify_key_type_int(val: Any, expected: str) -> None:
    assert _classify_key_type(val) == expected


def test_classify_key_type_bool() -> None:
    """bool is a subclass of int, but should be classified as 'str'."""
    assert _classify_key_type(True) == "str"
    assert _classify_key_type(False) == "str"


def test_classify_key_type_datetime() -> None:
    dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert _classify_key_type(dt) == "datetime"


def test_classify_key_type_str() -> None:
    assert _classify_key_type("abc") == "str"
    assert _classify_key_type("") == "str"
    assert _classify_key_type("123") == "str"


def test_classify_key_type_none() -> None:
    assert _classify_key_type(None) == "str"


@pytest.mark.parametrize("val", [3.14, 2.0])
def test_classify_key_type_float_like_int(val: Any) -> None:
    """Floats without __int__ method fall through; hasattr(int) path."""
    # Plain float has __int__ method
    assert _classify_key_type(val) == "int"


# ---------------------------------------------------------------------------
# _compute_int_chunks
# ---------------------------------------------------------------------------


def test_compute_int_chunks_small_range() -> None:
    """Range smaller than chunk_size produces a single chunk covering [min, max+1)."""
    chunks = _compute_int_chunks(min_val=1, max_val=10, chunk_size=100)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].key_start == 1
    assert chunks[0].key_end == 11  # max_val + 1


def test_compute_int_chunks_exact_division() -> None:
    """Range 0..99 divided into 10 chunks of size 10."""
    chunks = _compute_int_chunks(min_val=0, max_val=99, chunk_size=10)
    assert len(chunks) == 10
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert c.key_start == i * 10
        if i < 9:
            assert c.key_end == (i + 1) * 10
        else:
            assert c.key_end == 100  # max_val + 1


def test_compute_int_chunks_uneven() -> None:
    """Uneven range: 0..100 with chunk_size=30 produces 4 chunks."""
    chunks = _compute_int_chunks(min_val=0, max_val=100, chunk_size=30)
    span = 101
    num_chunks = max(1, math.ceil(span / 30))
    actual_size = math.ceil(span / num_chunks)

    assert len(chunks) == num_chunks
    for i, c in enumerate(chunks):
        assert c.key_start == i * actual_size
        if i < num_chunks - 1:
            assert c.key_end == (i + 1) * actual_size
        else:
            assert c.key_end == 101  # max_val + 1


def test_compute_int_chunks_zero_size() -> None:
    with pytest.raises(ValueError, match="chunk_size 必须为正数"):
        _compute_int_chunks(min_val=0, max_val=100, chunk_size=0)


def test_compute_int_chunks_negative_size() -> None:
    with pytest.raises(ValueError, match="chunk_size 必须为正数"):
        _compute_int_chunks(min_val=0, max_val=100, chunk_size=-10)


def test_compute_int_chunks_single_value() -> None:
    """min == max produces a single chunk."""
    chunks = _compute_int_chunks(min_val=5, max_val=5, chunk_size=10)
    assert len(chunks) == 1
    assert chunks[0].key_start == 5
    assert chunks[0].key_end == 6  # max_val + 1


# ---------------------------------------------------------------------------
# _compute_datetime_chunks
# ---------------------------------------------------------------------------


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def test_compute_datetime_chunks_range() -> None:
    """100-second range with chunk_size=30 produces 4 chunks, last has key_end=None."""
    min_val = _dt(1577836800.0)   # 2020-01-01 00:00:00 UTC
    max_val = _dt(1577836900.0)   # 2020-01-01 00:01:40 UTC
    chunks = _compute_datetime_chunks(min_val, max_val, chunk_size=30)

    total_seconds = 100.0
    num_chunks = max(1, math.ceil(total_seconds / 30))
    assert len(chunks) == num_chunks
    assert chunks[0].key_start == min_val
    assert chunks[-1].key_end is None

    for i, c in enumerate(chunks):
        assert c.chunk_index == i


def test_compute_datetime_chunks_single() -> None:
    """Single timestamp (min == max) produces one chunk with key_end=None."""
    val = _dt(1577836800.0)
    chunks = _compute_datetime_chunks(val, val, chunk_size=30)
    assert len(chunks) == 1
    assert chunks[0].key_start == val
    assert chunks[0].key_end is None
    assert chunks[0].chunk_index == 0


def test_compute_datetime_chunks_zero_size() -> None:
    val = _dt(1577836800.0)
    with pytest.raises(ValueError, match="chunk_size 必须为正数"):
        _compute_datetime_chunks(val, val, chunk_size=0)


def test_compute_datetime_chunks_utc_timezone() -> None:
    """Chunk boundaries are timezone-aware UTC datetimes."""
    min_val = _dt(1577836800.0)
    max_val = _dt(1577836900.0)
    chunks = _compute_datetime_chunks(min_val, max_val, chunk_size=30)

    for c in chunks:
        if c.key_start is not None:
            assert c.key_start.tzinfo is not None
            assert c.key_start.utcoffset() is not None
            offset = c.key_start.utcoffset()
            assert offset is not None and offset.total_seconds() == 0  # UTC
        if c.key_end is not None:
            assert c.key_end.tzinfo is not None
            assert c.key_end.utcoffset() is not None
            offset = c.key_end.utcoffset()
            assert offset is not None and offset.total_seconds() == 0  # UTC


def test_compute_datetime_chunks_ordered() -> None:
    """Chunk boundaries are monotonically increasing."""
    min_val = _dt(1577836800.0)
    max_val = _dt(1577836900.0)
    chunks = _compute_datetime_chunks(min_val, max_val, chunk_size=30)

    prev: datetime | None = None
    for c in chunks:
        if prev is not None and c.key_start is not None:
            assert c.key_start >= prev
        prev = c.key_start  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# detect_chunk_key — mock adapters
# ---------------------------------------------------------------------------


class _MockPGAdapter:
    db_type = "postgresql"


class _MockCHAdapter:
    db_type = "clickhouse"


class _PGCursor:
    """Minimal cursor that captures execute params and returns canned data."""

    def __init__(self, fetch_result: tuple[Any, ...] | None) -> None:
        self._fetch_result = fetch_result
        self.executed: list[Any] = []

    def execute(self, query: Any, params: Any = None) -> None:
        self.executed.append((query, params))

    def fetchone(self) -> Any:
        return self._fetch_result

    def close(self) -> None:
        pass

    def __enter__(self) -> _PGCursor:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _PGClient:
    def __init__(self, pk_column: str | None = None) -> None:
        self.pk_column = pk_column

    def cursor(self) -> _PGCursor:
        return _PGCursor(
            (self.pk_column,) if self.pk_column is not None else None,
        )


class _CHResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.result_rows = rows


class _CHClient:
    def __init__(self, pk_column: str | None = None) -> None:
        self.pk_column = pk_column

    def query(self, sql: str, parameters: Any = None) -> _CHResult:
        if self.pk_column is not None:
            return _CHResult([(self.pk_column,)])
        return _CHResult([])


def test_detect_chunk_key_pg() -> None:
    adapter = _MockPGAdapter()
    client = _PGClient(pk_column="id")
    result = detect_chunk_key(adapter, client, "users", "public")
    assert result == "id"


def test_detect_chunk_key_ch() -> None:
    adapter = _MockCHAdapter()
    client = _CHClient(pk_column="id")
    result = detect_chunk_key(adapter, client, "users", "default")
    assert result == "id"


def test_detect_chunk_key_no_pk_pg() -> None:
    adapter = _MockPGAdapter()
    client = _PGClient(pk_column=None)
    with pytest.raises(ValueError, match="未找到主键"):
        detect_chunk_key(adapter, client, "users", "public")


def test_detect_chunk_key_no_pk_ch() -> None:
    adapter = _MockCHAdapter()
    client = _CHClient(pk_column=None)
    with pytest.raises(ValueError, match="未找到主键"):
        detect_chunk_key(adapter, client, "users", "default")


def test_detect_chunk_key_unsupported_db_type() -> None:
    adapter = _MockPGAdapter()
    adapter.db_type = "mysql"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="不支持的数据库类型"):
        detect_chunk_key(adapter, object(), "users", "public")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# probe_range — mock adapters
# ---------------------------------------------------------------------------


class _ProbeCursor:
    def __init__(self, min_val: Any, max_val: Any) -> None:
        self._min_val = min_val
        self._max_val = max_val

    def execute(self, query: Any) -> None:
        pass

    def fetchone(self) -> tuple[Any, Any] | None:
        if self._min_val is None:
            return None
        return (self._min_val, self._max_val)

    def close(self) -> None:
        pass


class _ProbePGClient:
    def __init__(self, min_val: Any, max_val: Any) -> None:
        self._min_val = min_val
        self._max_val = max_val

    def cursor(self) -> _ProbeCursor:
        return _ProbeCursor(self._min_val, self._max_val)


class _ProbeCHResult:
    def __init__(self, min_val: Any, max_val: Any) -> None:
        self.result_rows = (
            [(min_val, max_val)] if min_val is not None else []
        )


class _ProbeCHClient:
    def __init__(self, min_val: Any, max_val: Any) -> None:
        self._min_val = min_val
        self._max_val = max_val

    def query(self, sql: str) -> _ProbeCHResult:
        return _ProbeCHResult(self._min_val, self._max_val)


def test_probe_range_pg() -> None:
    adapter = _MockPGAdapter()
    client = _ProbePGClient(min_val=1, max_val=100)
    min_v, max_v = probe_range(adapter, client, "users", "id", "public")
    assert min_v == 1
    assert max_v == 100


def test_probe_range_ch() -> None:
    adapter = _MockCHAdapter()
    client = _ProbeCHClient(min_val=1, max_val=100)
    min_v, max_v = probe_range(adapter, client, "users", "id", "default")
    assert min_v == 1
    assert max_v == 100


def test_probe_range_empty_pg() -> None:
    adapter = _MockPGAdapter()
    client = _ProbePGClient(min_val=None, max_val=None)
    min_v, max_v = probe_range(adapter, client, "users", "id", "public")
    assert min_v is None
    assert max_v is None


def test_probe_range_empty_ch() -> None:
    adapter = _MockCHAdapter()
    client = _ProbeCHClient(min_val=None, max_val=None)
    min_v, max_v = probe_range(adapter, client, "users", "id", "default")
    assert min_v is None
    assert max_v is None


# ---------------------------------------------------------------------------
# compute_chunks — integration with mock adapters
# ---------------------------------------------------------------------------


def test_compute_chunks_integration_pg() -> None:
    """Full pipeline: compute_chunks with mock PG adapter."""
    adapter = _MockPGAdapter()
    client = _ProbePGClient(min_val=0, max_val=99)
    cond = MigrationCondition(
        table_name="users", mode="where", chunk_key="id", chunk_size=10,
    )
    chunks = compute_chunks(adapter, client, "users", cond, "public")
    assert len(chunks) == 10
    for i, c in enumerate(chunks):
        assert c.key_start == i * 10
        assert c.key_end == (i + 1) * 10 if i < 9 else 100


def test_compute_chunks_integration_ch() -> None:
    """Full pipeline: compute_chunks with mock CH adapter."""
    adapter = _MockCHAdapter()
    client = _ProbeCHClient(min_val=0, max_val=99)
    cond = MigrationCondition(
        table_name="users", mode="where", chunk_key="id", chunk_size=10,
    )
    chunks = compute_chunks(adapter, client, "users", cond, "default")
    assert len(chunks) == 10
    for i, c in enumerate(chunks):
        assert c.key_start == i * 10
        assert c.key_end == (i + 1) * 10 if i < 9 else 100


def test_compute_chunks_empty_table() -> None:
    """Empty table returns single chunk with None bounds."""
    adapter = _MockPGAdapter()
    client = _ProbePGClient(min_val=None, max_val=None)
    cond = MigrationCondition(
        table_name="empty", mode="where", chunk_key="id",
    )
    chunks = compute_chunks(adapter, client, "empty", cond, "public")
    assert len(chunks) == 1
    assert chunks[0].key_start is None
    assert chunks[0].key_end is None
    assert chunks[0].chunk_index == 0


def test_compute_chunks_str_key() -> None:
    """String key returns single chunk with key_start=min_val, key_end=None."""
    adapter = _MockPGAdapter()
    client = _ProbePGClient(min_val="aaa", max_val="zzz")
    cond = MigrationCondition(
        table_name="users", mode="where", chunk_key="name",
    )
    chunks = compute_chunks(adapter, client, "users", cond, "public")
    assert len(chunks) == 1
    assert chunks[0].key_start == "aaa"
    assert chunks[0].key_end is None
