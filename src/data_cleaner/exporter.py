"""Write the cleaning result to a formatted, client-ready Excel workbook.

Sheets:
    * **Cleaned Data** - the clean table, with a styled header, frozen header
      row, filters, real Excel dates/numbers and sensible column widths.
    * **Rejected Rows** - rows that were removed, with original values and the
      reason, so they can be corrected at the source.
    * **Cleaning Summary** - the numbers from :class:`CleaningReport`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from data_cleaner.config import CleanerConfig
from data_cleaner.exceptions import OutputFileError
from data_cleaner.report import CleaningReport

if TYPE_CHECKING:  # avoid a circular import at runtime
    from data_cleaner.pipeline import CleaningResult

logger = logging.getLogger(__name__)

SHEET_CLEANED = "Cleaned Data"
SHEET_REJECTED = "Rejected Rows"
SHEET_SUMMARY = "Cleaning Summary"

HEADER_FILL = PatternFill(fill_type="solid", start_color="1F4E78", end_color="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color="1F4E78")
SECTION_FONT = Font(bold=True, size=12, color="1F4E78")
INTEGER_FORMAT = "#,##0"
MIN_COLUMN_WIDTH = 8
MAX_COLUMN_WIDTH = 60
_WIDTH_SAMPLE_ROWS = 500


def export_workbook(result: CleaningResult, output_path: str | Path, config: CleanerConfig) -> Path:
    """Write the three-sheet workbook and return its path.

    Raises:
        OutputFileError: wrong extension, or the file cannot be written
            (most often because it is open in Excel).
    """
    path = Path(output_path)
    if path.suffix.lower() != ".xlsx":
        raise OutputFileError(f"Output file must have a .xlsx extension: {path}")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            result.cleaned.to_excel(writer, sheet_name=SHEET_CLEANED, index=False)
            result.rejected.to_excel(writer, sheet_name=SHEET_REJECTED, index=False)
            _format_table(writer.sheets[SHEET_CLEANED], result.cleaned, config)
            _format_table(writer.sheets[SHEET_REJECTED], result.rejected, config)
            _write_summary(writer.book.create_sheet(SHEET_SUMMARY), result.report)
    except PermissionError as exc:
        raise OutputFileError(
            f"Cannot write {path}. If it is open in Excel, close it and try again."
        ) from exc
    except OSError as exc:
        raise OutputFileError(f"Cannot write {path}: {exc}") from exc

    logger.info("Saved cleaned workbook to %s", path)
    return path


def _format_table(sheet: Worksheet, frame: pd.DataFrame, config: CleanerConfig) -> None:
    """Style the header, freeze it, add filters, set number formats and widths."""
    _style_header_row(sheet[1])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for position, column in enumerate(frame.columns, start=1):
        letter = get_column_letter(position)
        series = frame[column]
        number_format = _number_format_for(series, config)
        if number_format:
            for (cell,) in sheet.iter_rows(min_row=2, min_col=position, max_col=position):
                cell.number_format = number_format
        sheet.column_dimensions[letter].width = _column_width(column, series)


def _number_format_for(series: pd.Series, config: CleanerConfig) -> str | None:
    if pd.api.types.is_datetime64_any_dtype(series):
        return config.excel_date_format
    if pd.api.types.is_bool_dtype(series):
        return None
    if pd.api.types.is_integer_dtype(series):
        return INTEGER_FORMAT
    if pd.api.types.is_float_dtype(series):
        return config.excel_number_format
    return None


def _column_width(header: str, series: pd.Series) -> float:
    """Approximate Excel's "AutoFit" from the header and a sample of values."""
    if pd.api.types.is_datetime64_any_dtype(series):
        longest = 10  # yyyy-mm-dd
    else:
        sample = series.head(_WIDTH_SAMPLE_ROWS)
        longest = max((len(str(v)) for v in sample if not pd.isna(v)), default=0)
        if pd.api.types.is_numeric_dtype(series):
            longest += longest // 3 + 3  # room for thousands separators and decimals
    width = max(len(str(header)), longest) + 2
    return float(min(max(width, MIN_COLUMN_WIDTH), MAX_COLUMN_WIDTH))


def _style_header_row(cells: Iterable) -> None:
    for cell in cells:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _write_summary(sheet: Worksheet, report: CleaningReport) -> None:
    """Lay out the cleaning report as a few small, readable tables."""
    sheet.append(["Data Cleaning Report"])
    sheet["A1"].font = TITLE_FONT
    sheet.append([f"Generated {datetime.now():%Y-%m-%d %H:%M}"])
    sheet.append([])

    _append_section(sheet, "Overview", ["Metric", "Value"], report.overview_rows())

    reasons = report.rejection_reasons.most_common() or [("No rows removed", 0)]
    _append_section(sheet, "Rows removed by reason", ["Reason", "Rows"], reasons)

    column_rows = [
        (
            column,
            stats.values_changed,
            stats.missing_filled,
            stats.invalid_values,
            stats.missing_after_cleaning,
        )
        for column, stats in report.column_stats.items()
    ]
    _append_section(
        sheet,
        "Column details",
        ["Column", "Values corrected", "Missing values filled", "Invalid values", "Blank in output"],
        column_rows,
    )

    if report.columns_renamed:
        _append_section(
            sheet, "Renamed columns", ["Original name", "New name"], report.columns_renamed.items()
        )

    sheet.column_dimensions["A"].width = 34
    for letter in "BCDE":
        sheet.column_dimensions[letter].width = 22


def _append_section(
    sheet: Worksheet, title: str, headers: Sequence[str], rows: Iterable[Sequence[object]]
) -> None:
    sheet.append([title])
    sheet.cell(row=sheet.max_row, column=1).font = SECTION_FONT
    sheet.append(list(headers))
    _style_header_row(sheet[sheet.max_row])
    for row in rows:
        sheet.append(list(row))
    sheet.append([])
