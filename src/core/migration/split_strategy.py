"""Deterministic chunk generation from SplitConfig without DB probes."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Literal

from core.migration.models import BindType, ChunkSpec, SplitConfig, SplitMode

ValueFormat = Literal["yyyy-MM-dd", "yyyyMMdd", "yyyyMM", "yyyy"]
Granularity = Literal["day", "month", "year"]
SplitModeKind = Literal["calendar", "partition_value"]

_TEMPLATE_TOKEN = re.compile(r"\{(yyyy-MM-dd|yyyyMMdd|yyyyMM|yyyy)\}")


def compute_split_chunks(cfg: SplitConfig) -> list[ChunkSpec]:
    """Generate chunks from SplitConfig without DB queries."""
    if cfg.mode == SplitMode.KEY_RANGE:
        raise NotImplementedError(
            "KEY_RANGE split mode is handled by legacy chunk_strategy"
        )

    _validate_range(cfg)

    if cfg.mode == SplitMode.CALENDAR:
        return _compute_calendar_chunks(cfg)
    if cfg.mode == SplitMode.PARTITION_VALUE:
        return _compute_partition_value_chunks(cfg)
    if cfg.mode == SplitMode.PHYSICAL_PARTITION:
        return _compute_physical_chunks(cfg)

    raise ValueError(f"unsupported split mode: {cfg.mode}")


def merge_extra_where(where_sql: str, extra_where: str) -> str:
    """AND-combine where_sql with extra_where if both non-empty."""
    left = where_sql.strip()
    right = extra_where.strip()
    if left and right:
        return f"({left}) AND ({right})"
    return left or right


def parse_range_value(value: str, fmt: ValueFormat) -> date | int:
    """Parse a range boundary string into a date or integer."""
    text = value.strip()
    if not text:
        raise ValueError("range value cannot be empty")
    if fmt == "yyyy-MM-dd":
        return datetime.strptime(text, "%Y-%m-%d").date()
    if fmt == "yyyyMMdd":
        return int(text)
    if fmt == "yyyyMM":
        return int(text)
    if fmt == "yyyy":
        return int(text)
    raise ValueError(f"unsupported value_format: {fmt}")


def iterate_range(
    range_start: date,
    range_end: date,
    granularity: Granularity,
    batch_size: int,
    *,
    mode: SplitModeKind,
) -> list[tuple[date, date]]:
    """Yield (start, end) pairs; calendar uses half-open end, partition inclusive."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if range_start > range_end:
        raise ValueError("range_start must not be after range_end")

    inclusive_end = range_end
    exclusive_upper = _advance_date(inclusive_end, granularity, 1)
    pairs: list[tuple[date, date]] = []
    cursor = range_start

    while cursor <= inclusive_end:
        chunk_end = _advance_date(cursor, granularity, batch_size)
        if mode == "calendar":
            chunk_end = min(chunk_end, exclusive_upper)
            pairs.append((cursor, chunk_end))
            cursor = chunk_end
        else:
            last_inclusive = min(
                _advance_date(cursor, granularity, batch_size) - timedelta(days=1),
                inclusive_end,
            )
            pairs.append((cursor, last_inclusive))
            cursor = _advance_date(last_inclusive, granularity, 1)

    return pairs


def build_where_sql(
    bind_type: BindType,
    bind_target: str,
    start: date | int,
    end: date | int,
    value_format: ValueFormat,
    mode: SplitModeKind,
) -> str:
    """Build a WHERE fragment for one chunk."""
    if not bind_target.strip():
        raise ValueError("bind_target is required")

    start_lit = _format_sql_literal(start, value_format)
    end_lit = _format_sql_literal(end, value_format)

    if bind_type == BindType.COLUMN:
        if mode == "calendar":
            return f"{bind_target} >= {start_lit} AND {bind_target} < {end_lit}"
        return f"{bind_target} >= {start_lit} AND {bind_target} <= {end_lit}"

    if bind_type == BindType.EXPRESSION:
        if mode == "calendar":
            return (
                f"{bind_target} >= {start_lit} AND {bind_target} < {end_lit}"
            )
        return (
            f"{bind_target} >= {start_lit} AND {bind_target} <= {end_lit}"
        )

    raise ValueError(f"bind_type {bind_type} does not support where_sql generation")


def _compute_calendar_chunks(cfg: SplitConfig) -> list[ChunkSpec]:
    start = _to_date(parse_range_value(cfg.range_start, cfg.value_format))
    end = _to_date(parse_range_value(cfg.range_end, cfg.value_format))
    intervals = iterate_range(
        start,
        end,
        cfg.granularity,
        cfg.batch_size,
        mode="calendar",
    )
    return _build_chunks_from_intervals(cfg, intervals, mode="calendar")


def _compute_partition_value_chunks(cfg: SplitConfig) -> list[ChunkSpec]:
    start = _to_date(parse_range_value(cfg.range_start, cfg.value_format))
    end = _to_date(parse_range_value(cfg.range_end, cfg.value_format))
    intervals = iterate_range(
        start,
        end,
        cfg.granularity,
        cfg.batch_size,
        mode="partition_value",
    )
    return _build_chunks_from_intervals(cfg, intervals, mode="partition_value")


def _compute_physical_chunks(cfg: SplitConfig) -> list[ChunkSpec]:
    if cfg.bind_type != BindType.NAME_TEMPLATE:
        raise NotImplementedError(
            "PHYSICAL_PARTITION with METADATA_LIST is handled in Task 3"
        )
    if not cfg.bind_target.strip():
        raise ValueError("bind_target template is required")

    start = _to_date(parse_range_value(cfg.range_start, cfg.value_format))
    end = _to_date(parse_range_value(cfg.range_end, cfg.value_format))
    names: list[str] = []
    cursor = start
    while cursor <= end:
        names.append(_render_template(cfg.bind_target, cursor, cfg.value_format))
        cursor += timedelta(days=1)

    chunks: list[ChunkSpec] = []
    batch = max(cfg.batch_size, 1)
    for index in range(0, len(names), batch):
        batch_names = names[index : index + batch]
        label = _format_label_from_names(batch_names, cfg.value_format)
        where_sql = merge_extra_where("", cfg.extra_where)
        chunks.append(
            ChunkSpec(
                chunk_index=len(chunks),
                label=label,
                where_sql=where_sql,
                physical_targets=batch_names,
            )
        )
    return chunks


def _build_chunks_from_intervals(
    cfg: SplitConfig,
    intervals: list[tuple[date, date]],
    *,
    mode: SplitModeKind,
) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    for chunk_index, (start, end) in enumerate(intervals):
        if mode == "calendar":
            label_end = end - timedelta(days=1)
            label = _format_label(start, label_end, cfg.value_format)
            where_start = _to_bound_value(start, cfg.value_format)
            where_end = _to_bound_value(end, cfg.value_format)
        else:
            label = _format_label(start, end, cfg.value_format)
            where_start = _to_bound_value(start, cfg.value_format)
            where_end = _to_bound_value(end, cfg.value_format)

        where_sql = build_where_sql(
            cfg.bind_type,
            cfg.bind_target,
            where_start,
            where_end,
            cfg.value_format,
            mode,
        )
        where_sql = merge_extra_where(where_sql, cfg.extra_where)
        chunks.append(
            ChunkSpec(
                chunk_index=chunk_index,
                label=label,
                where_sql=where_sql,
            )
        )
    return chunks


def _validate_range(cfg: SplitConfig) -> None:
    if not cfg.range_start.strip():
        raise ValueError("range_start is required")
    if not cfg.range_end.strip():
        raise ValueError("range_end is required")

    start = parse_range_value(cfg.range_start, cfg.value_format)
    end = parse_range_value(cfg.range_end, cfg.value_format)
    if _compare_values(start, end) > 0:
        raise ValueError("range_start must not be after range_end")

    if cfg.mode in (SplitMode.CALENDAR, SplitMode.PARTITION_VALUE):
        if not cfg.bind_target.strip():
            raise ValueError("bind_target is required")
        if cfg.batch_size < 1:
            raise ValueError("batch_size must be at least 1")


def _compare_values(left: date | int, right: date | int) -> int:
    left_key = _to_date(left) if isinstance(left, int) else left
    right_key = _to_date(right) if isinstance(right, int) else right
    if left_key < right_key:
        return -1
    if left_key > right_key:
        return 1
    return 0


def _to_date(value: date | int) -> date:
    if isinstance(value, date):
        return value
    text = str(value)
    if len(text) == 8:
        return datetime.strptime(text, "%Y%m%d").date()
    if len(text) == 6:
        return datetime.strptime(text, "%Y%m").date()
    if len(text) == 4:
        return date(int(text), 1, 1)
    raise ValueError(f"cannot convert {value!r} to date")


def _to_bound_value(value: date, fmt: ValueFormat) -> date | int:
    if fmt == "yyyy-MM-dd":
        return value
    if fmt == "yyyyMMdd":
        return int(value.strftime("%Y%m%d"))
    if fmt == "yyyyMM":
        return int(value.strftime("%Y%m"))
    if fmt == "yyyy":
        return value.year
    raise ValueError(f"unsupported value_format: {fmt}")


def _format_sql_literal(value: date | int, fmt: ValueFormat) -> str:
    if fmt == "yyyy-MM-dd":
        if isinstance(value, date):
            return f"'{value.isoformat()}'"
        return f"'{_to_date(value).isoformat()}'"
    return str(value)


def _format_label(start: date, end: date, fmt: ValueFormat) -> str:
    return f"{_format_display(start, fmt)}~{_format_display(end, fmt)}"


def _format_display(value: date, fmt: ValueFormat) -> str:
    if fmt == "yyyy-MM-dd":
        return value.isoformat()
    if fmt == "yyyyMMdd":
        return value.strftime("%Y%m%d")
    if fmt == "yyyyMM":
        return value.strftime("%Y%m")
    if fmt == "yyyy":
        return str(value.year)
    raise ValueError(f"unsupported value_format: {fmt}")


def _format_label_from_names(names: list[str], fmt: ValueFormat) -> str:
    if not names:
        return ""
    if fmt == "yyyyMMdd" and all(name.endswith("_") is False for name in names):
        suffixes = [name.rsplit("_", 1)[-1] for name in names]
        if all(suffix.isdigit() and len(suffix) == 8 for suffix in suffixes):
            return f"{suffixes[0]}~{suffixes[-1]}"
    return f"{names[0]}~{names[-1]}"


def _render_template(template: str, value: date, fmt: ValueFormat) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        return _format_display(value, token)  # type: ignore[arg-type]

    return _TEMPLATE_TOKEN.sub(replace, template)


def _advance_date(value: date, granularity: Granularity, units: int) -> date:
    if units == 0:
        return value
    if granularity == "day":
        return value + timedelta(days=units)
    if granularity == "month":
        return _add_months(value, units)
    if granularity == "year":
        return date(value.year + units, value.month, value.day)
    raise ValueError(f"unsupported granularity: {granularity}")


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
