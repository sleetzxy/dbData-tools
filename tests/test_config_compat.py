"""Tests for migration config compatibility layer."""

from __future__ import annotations

from core.migration.config_compat import (
    apply_split_to_condition,
    legacy_to_split_config,
    split_config_from_dict,
    split_config_to_dict,
)
from core.migration.models import (
    BindType,
    MigrationCondition,
    SplitConfig,
    SplitMode,
)


def test_legacy_condition_to_split_config() -> None:
    """Old JSON without split maps chunk_key/where_clause to KEY_RANGE."""
    cond = MigrationCondition(
        table_name="t",
        mode="where",
        chunk_key="id",
        chunk_size=1000,
        where_clause="x=1",
    )
    split = legacy_to_split_config(cond)
    assert split.mode == SplitMode.KEY_RANGE
    assert split.extra_where == "x=1"


def test_legacy_without_chunk_key_keeps_existing_split() -> None:
    """No chunk_key means the existing split config is returned unchanged."""
    cond = MigrationCondition(
        table_name="t",
        mode="where",
        where_clause="x=1",
        split=SplitConfig(
            mode=SplitMode.CALENDAR,
            range_start="20240101",
            range_end="20240131",
            bind_target="dt",
        ),
    )
    split = legacy_to_split_config(cond)
    assert split.mode == SplitMode.CALENDAR
    assert split.range_start == "20240101"
    assert split.extra_where == ""


def test_legacy_with_range_does_not_override() -> None:
    """Configured split range takes precedence over legacy chunk_key."""
    cond = MigrationCondition(
        table_name="t",
        mode="where",
        chunk_key="id",
        where_clause="x=1",
        split=SplitConfig(
            mode=SplitMode.PARTITION_VALUE,
            range_start="20240101",
            range_end="20240131",
            bind_target="p_date",
        ),
    )
    split = legacy_to_split_config(cond)
    assert split.mode == SplitMode.PARTITION_VALUE
    assert split.range_start == "20240101"
    assert split.extra_where == ""


def test_split_config_round_trip_dict() -> None:
    """split_config_to_dict and split_config_from_dict round-trip all fields."""
    original = SplitConfig(
        mode=SplitMode.CALENDAR,
        range_start="2024-06-01",
        range_end="2024-06-30",
        value_format="yyyy-MM-dd",
        granularity="month",
        bind_type=BindType.EXPRESSION,
        bind_target="toYYYYMMDD(event_time)",
        batch_size=7,
        extra_where="status = 1",
    )
    restored = split_config_from_dict(split_config_to_dict(original))
    assert restored == original


def test_apply_split_to_condition_parses_gui_dict() -> None:
    """apply_split_to_condition builds SplitConfig from nested range/mode fields."""
    cond = MigrationCondition(table_name="orders", mode="where")
    split_dict = {
        "mode": "partition_value",
        "range": {"start": "20240601", "end": "20240630"},
        "value_format": "yyyyMMdd",
        "granularity": "day",
        "bind_type": "column",
        "bind_target": "p_date",
        "batch_size": 3,
        "extra_where": "active = true",
    }
    updated = apply_split_to_condition(cond, split_dict)
    assert updated.split.mode == SplitMode.PARTITION_VALUE
    assert updated.split.range_start == "20240601"
    assert updated.split.range_end == "20240630"
    assert updated.split.bind_type == BindType.COLUMN
    assert updated.split.bind_target == "p_date"
    assert updated.split.batch_size == 3
    assert updated.split.extra_where == "active = true"
    assert updated.table_name == "orders"


def test_split_config_from_dict_accepts_flat_range_fields() -> None:
    """Flat range_start/range_end keys are also supported."""
    split = split_config_from_dict(
        {
            "mode": "physical",
            "range_start": "20240101",
            "range_end": "20240110",
            "bind_type": "name_template",
            "bind_target": "orders_{yyyyMMdd}",
        }
    )
    assert split.mode == SplitMode.PHYSICAL_PARTITION
    assert split.range_start == "20240101"
    assert split.range_end == "20240110"
    assert split.bind_type == BindType.NAME_TEMPLATE
