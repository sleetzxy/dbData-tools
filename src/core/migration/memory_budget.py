"""Adaptive batch sizing from a memory budget and sampled row width."""

from __future__ import annotations

from dataclasses import dataclass

from core.migration.models import MemoryBudgetConfig

_MB = 1024 * 1024


@dataclass
class MemoryBudget:
    """Compute batch rows and buffer size from memory limits."""

    config: MemoryBudgetConfig

    def compute_batch_rows(self, avg_row_bytes: int) -> int:
        """batch_rows = clamp(limit_mb * 1024^2 * 0.5 / avg_row_bytes, min, max)."""
        row_bytes = max(avg_row_bytes, 1)
        half_budget = self.config.limit_mb * _MB * 0.5
        raw = int(half_budget / row_bytes)
        return max(
            self.config.min_batch_rows,
            min(raw, self.config.max_batch_rows),
        )

    @property
    def buffer_bytes(self) -> int:
        """limit_mb * 0.25 * 1024^2."""
        return int(self.config.limit_mb * 0.25 * _MB)

    def estimate_avg_row_bytes(self, sample_rows: list[tuple]) -> int:
        """Estimate bytes per row from sample; min 1 if empty."""
        if not sample_rows:
            return 1

        total_bytes = sum(_estimate_row_bytes(row) for row in sample_rows)
        return max(total_bytes // len(sample_rows), 1)


def _estimate_row_bytes(row: tuple) -> int:
    total = 0
    for value in row:
        if value is None:
            total += 4
        elif isinstance(value, (bytes, bytearray, memoryview)):
            total += len(value)
        elif isinstance(value, str):
            total += len(value.encode("utf-8"))
        else:
            total += len(str(value).encode("utf-8"))
    return max(total, 1)
