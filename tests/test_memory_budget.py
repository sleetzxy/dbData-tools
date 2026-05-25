"""Tests for MemoryBudget adaptive batch sizing."""

from __future__ import annotations

from core.migration.memory_budget import MemoryBudget
from core.migration.models import MemoryBudgetConfig


def test_compute_batch_rows_wide_table_clamps_to_min() -> None:
    """Very wide rows yield batch below min and clamp to min_batch_rows."""
    budget = MemoryBudget(MemoryBudgetConfig(limit_mb=512))
    rows = budget.compute_batch_rows(avg_row_bytes=5_000_000)
    assert rows == 100


def test_compute_batch_rows_normal_rows() -> None:
    """Moderate row width yields a batch within min/max bounds."""
    budget = MemoryBudget(MemoryBudgetConfig(limit_mb=512))
    rows = budget.compute_batch_rows(avg_row_bytes=5_000)
    assert 100 < rows <= 100_000
    assert rows == 53_687


def test_buffer_bytes_for_512mb() -> None:
    """512 MB limit reserves 128 MB (25%) for buffer bytes."""
    budget = MemoryBudget(MemoryBudgetConfig(limit_mb=512))
    expected = int(512 * 0.25 * 1024 * 1024)
    assert budget.buffer_bytes == expected
    assert budget.buffer_bytes == 134_217_728


def test_estimate_avg_row_bytes_empty_sample_returns_at_least_one() -> None:
    """Empty sample must not divide by zero downstream."""
    budget = MemoryBudget(MemoryBudgetConfig())
    assert budget.estimate_avg_row_bytes([]) >= 1


def test_estimate_avg_row_bytes_from_sample() -> None:
    """Average row bytes reflects sampled tuple payload sizes."""
    budget = MemoryBudget(MemoryBudgetConfig())
    sample = [("a" * 100, 1), ("b" * 100, 2)]
    avg = budget.estimate_avg_row_bytes(sample)
    assert avg >= 100
