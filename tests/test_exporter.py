"""Tests for the Excel workbook export."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from data_cleaner.config import CleanerConfig
from data_cleaner.exceptions import OutputFileError
from data_cleaner.exporter import SHEET_CLEANED, SHEET_REJECTED, SHEET_SUMMARY, export_workbook
from data_cleaner.pipeline import CleaningResult, clean_dataframe


@pytest.fixture
def result(raw_customers: pd.DataFrame, customer_config: CleanerConfig) -> CleaningResult:
    return clean_dataframe(raw_customers, customer_config, input_name="customers.csv")


def test_workbook_has_three_formatted_sheets(
    result: CleaningResult, customer_config: CleanerConfig, tmp_path: Path
) -> None:
    path = export_workbook(result, tmp_path / "nested" / "out.xlsx", customer_config)
    workbook = load_workbook(path)
    assert workbook.sheetnames == [SHEET_CLEANED, SHEET_REJECTED, SHEET_SUMMARY]

    cleaned = workbook[SHEET_CLEANED]
    assert cleaned.max_row == 1 + len(result.cleaned)
    assert cleaned.freeze_panes == "A2"
    assert cleaned.auto_filter.ref == cleaned.dimensions
    assert cleaned["A1"].value == "customer_id"
    assert cleaned["A1"].font.bold

    headers = [cell.value for cell in cleaned[1]]
    date_cell = cleaned.cell(row=2, column=headers.index("signup_date") + 1)
    assert isinstance(date_cell.value, datetime)
    assert date_cell.number_format == "yyyy-mm-dd"
    money_cell = cleaned.cell(row=2, column=headers.index("total_spent") + 1)
    assert money_cell.value == pytest.approx(1234.5)
    assert money_cell.number_format == "#,##0.00"
    phone_cell = cleaned.cell(row=2, column=headers.index("phone_no") + 1)
    assert phone_cell.value == "2125550147"  # stays text, no scientific notation


def test_rejected_and_summary_sheets(
    result: CleaningResult, customer_config: CleanerConfig, tmp_path: Path
) -> None:
    workbook = load_workbook(export_workbook(result, tmp_path / "out.xlsx", customer_config))
    rejected = workbook[SHEET_REJECTED]
    assert [rejected["A1"].value, rejected["B1"].value] == ["source_row", "rejection_reason"]
    assert rejected.max_row == 1 + len(result.rejected)

    summary_values = [
        cell.value for row in workbook[SHEET_SUMMARY].iter_rows() for cell in row if cell.value
    ]
    assert "Data Cleaning Report" in summary_values
    assert "Clean rows written" in summary_values
    assert "Duplicate record" in summary_values
    assert "Renamed columns" in summary_values


def test_empty_result_still_exports(customer_config: CleanerConfig, tmp_path: Path) -> None:
    empty = clean_dataframe(pd.DataFrame({"a": ["x", "x"]}, dtype=object), CleanerConfig())
    empty.cleaned = empty.cleaned.iloc[0:0]
    workbook = load_workbook(export_workbook(empty, tmp_path / "empty.xlsx", customer_config))
    assert workbook[SHEET_CLEANED].max_row == 1


def test_wrong_extension_raises(result: CleaningResult, customer_config, tmp_path: Path) -> None:
    with pytest.raises(OutputFileError, match=".xlsx"):
        export_workbook(result, tmp_path / "out.csv", customer_config)


def test_unwritable_location_raises(result: CleaningResult, customer_config, tmp_path: Path) -> None:
    blocker = tmp_path / "taken"
    blocker.write_text("a file, not a folder")
    with pytest.raises(OutputFileError, match="Cannot write"):
        export_workbook(result, blocker / "out.xlsx", customer_config)
