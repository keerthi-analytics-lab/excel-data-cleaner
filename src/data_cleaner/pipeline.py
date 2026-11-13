"""Orchestrate the cleaning steps.

Pipeline: load -> standardize column names -> clean text -> remove empty rows
-> handle missing values -> validate/convert typed columns -> separate rejected
rows -> remove duplicates -> export.

Nothing is silently deleted. Every row that does not reach the cleaned output
is either an empty row (counted) or written to the "Rejected Rows" sheet with
its *original* values and the reason, so the client can fix the source data.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Hashable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from data_cleaner.cleaners import (
    apply_case,
    apply_value_map,
    clean_text,
    convert_dates,
    convert_numbers,
    find_duplicates,
    standardize_column_names,
)
from data_cleaner.config import FILL_PREFIX, MISSING_DROP_ROW, CleanerConfig
from data_cleaner.exceptions import InputFileError, MissingColumnError
from data_cleaner.exporter import export_workbook
from data_cleaner.loader import load_table
from data_cleaner.report import CleaningReport
from data_cleaner.validators import find_missing_columns, is_valid_email, normalize_phone

logger = logging.getLogger(__name__)

ROW_COLUMN = "source_row"
REASON_COLUMN = "rejection_reason"
_FIRST_DATA_ROW = 2  # spreadsheet row number of the first data row (row 1 is the header)

Issues = dict[Hashable, list[str]]


@dataclass
class CleaningResult:
    """Output of a cleaning run."""

    cleaned: pd.DataFrame
    rejected: pd.DataFrame
    report: CleaningReport


def run_pipeline(
    input_path: str | Path,
    output_path: str | Path,
    config: CleanerConfig,
    sheet: str | None = None,
    delimiter: str = ",",
) -> CleaningResult:
    """Load a file, clean it, and write the formatted Excel workbook."""
    started = time.perf_counter()
    raw = load_table(input_path, sheet=sheet, delimiter=delimiter)
    result = clean_dataframe(raw, config, input_name=Path(input_path).name)
    result.report.duration_seconds = time.perf_counter() - started

    export_workbook(result, output_path, config)
    result.report.log_summary(logger)
    return result


def clean_dataframe(
    raw: pd.DataFrame, config: CleanerConfig, input_name: str = "<dataframe>"
) -> CleaningResult:
    """Clean a DataFrame of text values according to ``config``.

    Raises:
        MissingColumnError: if the config refers to columns that do not exist.
    """
    report = CleaningReport(input_name=input_name, rows_in=len(raw))
    frame = raw.copy()

    if config.standardize_column_names:
        new_names = standardize_column_names([str(c) for c in frame.columns])
        report.columns_renamed = {
            old: new for old, new in zip(frame.columns, new_names, strict=True) if old != new
        }
        frame.columns = new_names

    missing = find_missing_columns(config.referenced_columns(), frame.columns)
    if missing:
        raise MissingColumnError(
            f"Column(s) named in the config were not found in the input: {', '.join(missing)}. "
            f"Available columns: {', '.join(map(str, frame.columns))}"
        )

    data_columns = list(frame.columns)
    if ROW_COLUMN in data_columns:
        raise InputFileError(
            f"The input already has a column named '{ROW_COLUMN}', which this tool uses "
            "to track original row numbers. Please rename that column and try again."
        )
    frame.insert(0, ROW_COLUMN, range(_FIRST_DATA_ROW, _FIRST_DATA_ROW + len(frame)))
    original = frame.copy()  # untouched values, used for the Rejected Rows sheet
    issues: Issues = {}

    frame = _clean_text_columns(frame, data_columns, config, report)
    frame = _remove_empty_rows(frame, data_columns, report)
    frame = _handle_missing_values(frame, config, report, issues)
    frame = _validate_emails(frame, original, config, report, issues)
    frame = _validate_phones(frame, original, config, report, issues)
    frame = _convert_dates(frame, original, config, report, issues)
    frame = _convert_numbers(frame, original, config, report, issues)

    rejected_labels = [label for label in frame.index if label in issues]
    rejected_parts = [_rejected_rows(original, rejected_labels, issues)]
    report.rows_rejected = len(rejected_labels)
    frame = frame.drop(index=rejected_labels)

    frame, duplicate_rows = _remove_duplicates(frame, original, config, report)
    rejected_parts.append(duplicate_rows)

    for column in data_columns:
        report.stats_for(column).missing_after_cleaning = int(frame[column].isna().sum())

    cleaned = frame.drop(columns=ROW_COLUMN).reset_index(drop=True)
    non_empty_parts = [part for part in rejected_parts if not part.empty] or rejected_parts[:1]
    rejected = (
        pd.concat(non_empty_parts, ignore_index=True)
        .sort_values(ROW_COLUMN, kind="stable")
        .reset_index(drop=True)
    )
    report.rows_out = len(cleaned)
    for label, row_number in zip(rejected.index, rejected[ROW_COLUMN], strict=True):
        logger.debug("Row %s removed: %s", row_number, rejected.at[label, REASON_COLUMN])
    return CleaningResult(cleaned=cleaned, rejected=rejected, report=report)


# --------------------------------------------------------------------------- steps


def _clean_text_columns(
    frame: pd.DataFrame, columns: list[str], config: CleanerConfig, report: CleaningReport
) -> pd.DataFrame:
    """Trim whitespace, standardize missing markers, then apply case and value maps."""
    for column in columns:
        before = frame[column]
        cleaned = clean_text(before, config.missing_markers)
        if case := config.text_case.get(column):
            cleaned = cleaned.map(
                lambda value, c=case: apply_case(value, c, config.acronyms), na_action="ignore"
            )
        if mapping := config.value_maps.get(column):
            cleaned = cleaned.map(lambda value, m=mapping: apply_value_map(value, m), na_action="ignore")
        frame[column] = cleaned.astype(object)
        report.stats_for(column).values_changed += _count_changed(before, frame[column])
    return frame


def _remove_empty_rows(
    frame: pd.DataFrame, columns: list[str], report: CleaningReport
) -> pd.DataFrame:
    empty = frame[columns].isna().all(axis=1)
    report.empty_rows_removed = int(empty.sum())
    if report.empty_rows_removed:
        logger.info("Removed %d completely empty row(s)", report.empty_rows_removed)
    return frame.loc[~empty].copy()


def _handle_missing_values(
    frame: pd.DataFrame, config: CleanerConfig, report: CleaningReport, issues: Issues
) -> pd.DataFrame:
    """Reject rows missing required values, then apply per-column strategies."""
    for column in config.required_columns:
        _flag(issues, report, frame[column].isna(), f"Missing required value ({column})")

    for column, strategy in config.missing_values.items():
        missing = frame[column].isna()
        if strategy == MISSING_DROP_ROW:
            _flag(issues, report, missing, f"Missing value ({column})")
        elif strategy.startswith(FILL_PREFIX):
            fill_value = strategy[len(FILL_PREFIX) :]
            frame[column] = frame[column].where(~missing, fill_value)
            report.stats_for(column).missing_filled += int(missing.sum())
    return frame


def _validate_emails(
    frame: pd.DataFrame,
    original: pd.DataFrame,
    config: CleanerConfig,
    report: CleaningReport,
    issues: Issues,
) -> pd.DataFrame:
    for column in config.email_columns:
        before = frame[column]
        lowered = before.map(str.lower, na_action="ignore")
        valid = lowered.map(lambda value: pd.isna(value) or is_valid_email(value)).astype(bool)
        _flag(issues, report, ~valid, f"Invalid email ({column})", original[column])
        frame[column] = lowered.astype(object)
        stats = report.stats_for(column)
        stats.invalid_values += int((~valid).sum())
        stats.values_changed += _count_changed(before, lowered)
    return frame


def _validate_phones(
    frame: pd.DataFrame,
    original: pd.DataFrame,
    config: CleanerConfig,
    report: CleaningReport,
    issues: Issues,
) -> pd.DataFrame:
    for column in config.phone_columns:
        before = frame[column]
        normalized = before.map(
            lambda value: normalize_phone(value, config.phone_digits, config.phone_country_code),
            na_action="ignore",
        )
        invalid = before.notna() & normalized.isna()
        _flag(issues, report, invalid, f"Invalid phone number ({column})", original[column])
        frame[column] = normalized.astype(object)
        stats = report.stats_for(column)
        stats.invalid_values += int(invalid.sum())
        stats.values_changed += _count_changed(before[~invalid], normalized[~invalid])
    return frame


def _convert_dates(
    frame: pd.DataFrame,
    original: pd.DataFrame,
    config: CleanerConfig,
    report: CleaningReport,
    issues: Issues,
) -> pd.DataFrame:
    for column in config.date_columns:
        before = frame[column]
        dates, invalid = convert_dates(before, config.date_formats)
        _flag(issues, report, invalid, f"Unrecognised date ({column})", original[column])
        iso_text = dates.dt.strftime("%Y-%m-%d")
        reformatted = dates.notna() & (before.astype(str) != iso_text)
        frame[column] = dates
        stats = report.stats_for(column)
        stats.invalid_values += int(invalid.sum())
        stats.values_changed += int(reformatted.sum())
    return frame


def _convert_numbers(
    frame: pd.DataFrame,
    original: pd.DataFrame,
    config: CleanerConfig,
    report: CleaningReport,
    issues: Issues,
) -> pd.DataFrame:
    for column in config.number_columns:
        before = frame[column]
        numbers, invalid = convert_numbers(before)
        _flag(issues, report, invalid, f"Invalid number ({column})", original[column])
        # "Changed" = needed more than a plain float() to read, e.g. "$1,200.00".
        plain = before.map(lambda value: isinstance(value, str) and _is_plain_number(value))
        reformatted = numbers.notna() & ~plain.astype(bool)
        frame[column] = numbers
        stats = report.stats_for(column)
        stats.invalid_values += int(invalid.sum())
        stats.values_changed += int(reformatted.sum())
    return frame


def _remove_duplicates(
    frame: pd.DataFrame, original: pd.DataFrame, config: CleanerConfig, report: CleaningReport
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop duplicate records and return them as rejected rows with a reason."""
    duplicate_of = find_duplicates(frame, config.duplicate_subset, ROW_COLUMN)
    is_duplicate = duplicate_of.notna()
    report.duplicates_removed = int(is_duplicate.sum())
    if report.duplicates_removed:
        report.rejection_reasons["Duplicate record"] += report.duplicates_removed

    labels = list(frame.index[is_duplicate])
    reasons: Issues = {
        label: [f"Duplicate of row {int(duplicate_of.at[label])}"] for label in labels
    }
    return frame.drop(index=labels), _rejected_rows(original, labels, reasons)


# --------------------------------------------------------------------------- helpers


def _flag(
    issues: Issues,
    report: CleaningReport,
    mask: pd.Series,
    reason: str,
    raw_values: pd.Series | None = None,
) -> None:
    """Record ``reason`` for every row where ``mask`` is True."""
    labels = mask.index[mask.to_numpy(dtype=bool)]
    for label in labels:
        detail = reason if raw_values is None else f"{reason}: '{raw_values.at[label]}'"
        issues.setdefault(label, []).append(detail)
    if len(labels):
        report.rejection_reasons[reason] += len(labels)


def _rejected_rows(original: pd.DataFrame, labels: list[Hashable], issues: Issues) -> pd.DataFrame:
    """Build rejected rows: original values plus a readable reason column."""
    rows = original.loc[labels].copy()
    rows.insert(1, REASON_COLUMN, ["; ".join(issues[label]) for label in labels])
    return rows


def _as_comparable(value: object) -> str | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)) or value == "":
        return None
    return str(value)


def _count_changed(before: pd.Series, after: pd.Series) -> int:
    """Count cells whose value differs between two aligned columns."""
    return sum(
        _as_comparable(old) != _as_comparable(new) for old, new in zip(before, after, strict=True)
    )


def _is_plain_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
