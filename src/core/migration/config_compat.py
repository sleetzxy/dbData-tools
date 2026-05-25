"""旧迁移配置与 SplitConfig 之间的兼容转换。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.migration.models import (
    BindType,
    MigrationCondition,
    SplitConfig,
    SplitMode,
)


def _split_has_range(split: SplitConfig) -> bool:
    return bool(split.range_start.strip() and split.range_end.strip())


def _parse_split_mode(value: Any) -> SplitMode:
    if value is None:
        return SplitMode.PARTITION_VALUE
    if isinstance(value, SplitMode):
        return value
    return SplitMode(str(value))


def _parse_bind_type(value: Any) -> BindType:
    if value is None:
        return BindType.COLUMN
    if isinstance(value, BindType):
        return value
    return BindType(str(value))


def split_config_from_dict(data: dict[str, Any]) -> SplitConfig:
    """Build SplitConfig from a GUI persistence dict."""
    range_data = data.get("range") or {}
    range_start = data.get("range_start", range_data.get("start", ""))
    range_end = data.get("range_end", range_data.get("end", ""))

    return SplitConfig(
        mode=_parse_split_mode(data.get("mode")),
        range_start=str(range_start),
        range_end=str(range_end),
        value_format=data.get("value_format", "yyyyMMdd"),
        granularity=data.get("granularity", "day"),
        bind_type=_parse_bind_type(data.get("bind_type")),
        bind_target=str(data.get("bind_target", "")),
        batch_size=int(data.get("batch_size", 1)),
        extra_where=str(data.get("extra_where", "")),
    )


def legacy_to_split_config(cond: MigrationCondition) -> SplitConfig:
    """Map old chunk_key/chunk_size/where_clause to SplitConfig KEY_RANGE mode."""
    split = cond.split
    if not _split_has_range(split) and cond.chunk_key.strip():
        return SplitConfig(
            mode=SplitMode.KEY_RANGE,
            extra_where=cond.where_clause,
        )
    return split


def apply_split_to_condition(
    cond: MigrationCondition,
    split_dict: dict[str, Any],
) -> MigrationCondition:
    """Build SplitConfig from GUI JSON dict and attach to the condition."""
    split = split_config_from_dict(split_dict)
    return replace(cond, split=split)


def split_config_to_dict(split: SplitConfig) -> dict[str, Any]:
    """Serialize SplitConfig for GUI persistence."""
    return {
        "mode": split.mode.value,
        "range": {
            "start": split.range_start,
            "end": split.range_end,
        },
        "value_format": split.value_format,
        "granularity": split.granularity,
        "bind_type": split.bind_type.value,
        "bind_target": split.bind_target,
        "batch_size": split.batch_size,
        "extra_where": split.extra_where,
    }
