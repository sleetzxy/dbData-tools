"""Tests for deterministic split_strategy chunk generation."""

from __future__ import annotations

import pytest

from core.migration.models import BindType, SplitConfig, SplitMode
from core.migration.split_strategy import compute_split_chunks, merge_extra_where


def test_compute_calendar_chunks_june_daily_batch7() -> None:
    """2024-06-01 to 2024-06-30, day granularity, batch 7 -> 5 chunks."""
    cfg = SplitConfig(
        mode=SplitMode.CALENDAR,
        range_start="2024-06-01",
        range_end="2024-06-30",
        value_format="yyyy-MM-dd",
        granularity="day",
        bind_type=BindType.COLUMN,
        bind_target="created_at",
        batch_size=7,
    )
    chunks = compute_split_chunks(cfg)
    assert len(chunks) == 5
    assert chunks[0].label == "2024-06-01~2024-06-07"
    assert (
        "created_at >= '2024-06-01'" in chunks[0].where_sql
        and "created_at < '2024-06-08'" in chunks[0].where_sql
    )
    assert chunks[4].label == "2024-06-29~2024-06-30"
    assert "created_at < '2024-07-01'" in chunks[4].where_sql


def test_compute_partition_value_yyyyMMdd() -> None:
    """20240601-20240630 batch 7 -> 5 chunks with inclusive int bounds."""
    cfg = SplitConfig(
        mode=SplitMode.PARTITION_VALUE,
        range_start="20240601",
        range_end="20240630",
        value_format="yyyyMMdd",
        bind_type=BindType.COLUMN,
        bind_target="p_date",
        batch_size=7,
    )
    chunks = compute_split_chunks(cfg)
    assert len(chunks) == 5
    assert "20240601" in chunks[0].label
    assert "20240607" in chunks[0].label
    assert "p_date >= 20240601" in chunks[0].where_sql
    assert "p_date <= 20240607" in chunks[0].where_sql
    assert chunks[4].label == "20240629~20240630"


def test_compute_physical_template() -> None:
    """Template orders_{yyyyMMdd} over 6 days with batch 2."""
    cfg = SplitConfig(
        mode=SplitMode.PHYSICAL_PARTITION,
        range_start="20240601",
        range_end="20240606",
        value_format="yyyyMMdd",
        bind_type=BindType.NAME_TEMPLATE,
        bind_target="orders_{yyyyMMdd}",
        batch_size=2,
    )
    chunks = compute_split_chunks(cfg)
    assert len(chunks) == 3
    assert chunks[0].physical_targets == ["orders_20240601", "orders_20240602"]
    assert chunks[1].physical_targets == ["orders_20240603", "orders_20240604"]
    assert chunks[2].physical_targets == ["orders_20240605", "orders_20240606"]
    assert chunks[0].where_sql == ""


def test_merge_extra_where() -> None:
    """merge_extra_where AND-combines non-empty clauses."""
    assert merge_extra_where("", "") == ""
    assert merge_extra_where("a = 1", "") == "a = 1"
    assert merge_extra_where("", "b = 2") == "b = 2"
    assert merge_extra_where("a = 1", "b = 2") == "(a = 1) AND (b = 2)"


def test_empty_range_raises_or_returns_single_empty_chunk() -> None:
    """Invalid or empty range raises ValueError."""
    cfg = SplitConfig(
        mode=SplitMode.CALENDAR,
        range_start="",
        range_end="2024-06-30",
        value_format="yyyy-MM-dd",
        bind_target="created_at",
    )
    with pytest.raises(ValueError, match="range_start"):
        compute_split_chunks(cfg)

    cfg_inverted = SplitConfig(
        mode=SplitMode.PARTITION_VALUE,
        range_start="20240630",
        range_end="20240601",
        value_format="yyyyMMdd",
        bind_target="p_date",
    )
    with pytest.raises(ValueError, match="range_start"):
        compute_split_chunks(cfg_inverted)


def test_compute_split_chunks_applies_extra_where() -> None:
    """extra_where is merged into each chunk where_sql."""
    cfg = SplitConfig(
        mode=SplitMode.PARTITION_VALUE,
        range_start="20240601",
        range_end="20240607",
        value_format="yyyyMMdd",
        bind_type=BindType.COLUMN,
        bind_target="p_date",
        batch_size=7,
        extra_where="status = 'active'",
    )
    chunks = compute_split_chunks(cfg)
    assert len(chunks) == 1
    assert "p_date >= 20240601" in chunks[0].where_sql
    assert "status = 'active'" in chunks[0].where_sql


def test_key_range_raises_not_implemented() -> None:
    """KEY_RANGE defers to legacy chunk_strategy."""
    cfg = SplitConfig(mode=SplitMode.KEY_RANGE)
    with pytest.raises(NotImplementedError, match="KEY_RANGE"):
        compute_split_chunks(cfg)
