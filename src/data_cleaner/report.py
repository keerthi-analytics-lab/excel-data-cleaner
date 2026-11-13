"""Collect statistics about a cleaning run.

The report is what makes the tool client-friendly: instead of "I cleaned your
file", the client receives exact numbers - how many rows were removed and why,
and how many values were corrected in each column.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class ColumnStats:
    """Per-column counters."""

    values_changed: int = 0
    missing_filled: int = 0
    invalid_values: int = 0
    missing_after_cleaning: int = 0


@dataclass
class CleaningReport:
    """Summary of one cleaning run.

    Row accounting always balances:
    ``rows_in = empty_rows_removed + rows_rejected + duplicates_removed + rows_out``.
    """

    input_name: str
    rows_in: int = 0
    empty_rows_removed: int = 0
    rows_rejected: int = 0
    duplicates_removed: int = 0
    rows_out: int = 0
    columns_renamed: dict[str, str] = field(default_factory=dict)
    column_stats: dict[str, ColumnStats] = field(default_factory=dict)
    rejection_reasons: Counter[str] = field(default_factory=Counter)
    duration_seconds: float = 0.0

    def stats_for(self, column: str) -> ColumnStats:
        """Return (creating if needed) the counters for ``column``."""
        return self.column_stats.setdefault(column, ColumnStats())

    def overview_rows(self) -> list[tuple[str, object]]:
        """Key metrics as (label, value) pairs, ready for a table or log."""
        return [
            ("Input file", self.input_name),
            ("Rows read", self.rows_in),
            ("Empty rows removed", self.empty_rows_removed),
            ("Rows rejected (invalid data)", self.rows_rejected),
            ("Duplicate rows removed", self.duplicates_removed),
            ("Clean rows written", self.rows_out),
            ("Columns renamed", len(self.columns_renamed)),
            ("Processing time (seconds)", round(self.duration_seconds, 2)),
        ]

    def log_summary(self, logger: logging.Logger) -> None:
        """Write a short human-readable summary to ``logger``."""
        logger.info("Cleaning summary:")
        for label, value in self.overview_rows()[1:]:
            logger.info("  %-30s %s", label, value)
        for reason, count in self.rejection_reasons.most_common():
            logger.info("  - %s: %d row(s)", reason, count)
