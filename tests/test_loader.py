"""Tests for reading CSV and Excel files."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from data_cleaner.exceptions import EmptyInputError, InputFileError
from data_cleaner.loader import load_table


def _make_workbook(path: Path) -> Path:
    workbook = Workbook()
    first = workbook.active
    first.title = "Summary"
    first.append(["note"])
    first.append(["ignore me"])
    orders = workbook.create_sheet("Orders")
    orders.append(["Order ID", "Qty"])
    orders.append(["A-1", 3])
    orders.append(["A-2", None])
    workbook.save(path)
    return path


def test_reads_csv_as_text(write_text) -> None:
    path = write_text("data.csv", "id,zip,amount\n1,00123,1.50\n2,02134,\n")
    frame = load_table(path)
    assert list(frame.columns) == ["id", "zip", "amount"]
    assert frame["zip"].tolist() == ["00123", "02134"]  # leading zeros kept
    assert frame["amount"].tolist() == ["1.50", ""]  # nothing converted yet
    assert frame.dtypes.eq(object).all()


def test_reads_selected_excel_sheet(tmp_path: Path) -> None:
    path = _make_workbook(tmp_path / "book.xlsx")
    frame = load_table(path, sheet="Orders")
    assert list(frame.columns) == ["Order ID", "Qty"]
    assert frame.loc[0, "Qty"] == "3"
    assert pd.isna(frame.loc[1, "Qty"]) or frame.loc[1, "Qty"] == ""


def test_reads_first_sheet_by_default(tmp_path: Path) -> None:
    frame = load_table(_make_workbook(tmp_path / "book.xlsx"))
    assert list(frame.columns) == ["note"]


def test_missing_sheet_raises(tmp_path: Path) -> None:
    path = _make_workbook(tmp_path / "book.xlsx")
    with pytest.raises(InputFileError, match="Could not read"):
        load_table(path, sheet="Missing")


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(InputFileError, match="not found"):
        load_table(tmp_path / "missing.csv")


def test_directory_is_not_a_file(tmp_path: Path) -> None:
    with pytest.raises(InputFileError, match="not found"):
        load_table(tmp_path)


def test_unsupported_extension_raises(write_text) -> None:
    with pytest.raises(InputFileError, match="Unsupported file type '.txt'"):
        load_table(write_text("notes.txt", "a,b\n1,2\n"))


def test_zero_byte_file_raises(write_text) -> None:
    with pytest.raises(EmptyInputError, match="0 bytes"):
        load_table(write_text("empty.csv", ""))


def test_blank_lines_only_raises(write_text) -> None:
    with pytest.raises(EmptyInputError):
        load_table(write_text("blank.csv", "\n\n\n"))


def test_header_only_raises(write_text) -> None:
    with pytest.raises(EmptyInputError, match="no data rows"):
        load_table(write_text("header.csv", "name,email\n"))


def test_cp1252_fallback(write_text) -> None:
    path = write_text("legacy.csv", "city\nCafé Town\n", encoding="cp1252")
    assert load_table(path)["city"].tolist() == ["Café Town"]


def test_utf8_bom_is_stripped_from_header(write_text) -> None:
    path = write_text("bom.csv", "name\nZoë\n", encoding="utf-8-sig")
    frame = load_table(path)
    assert list(frame.columns) == ["name"]
    assert frame["name"].tolist() == ["Zoë"]


def test_custom_delimiter(write_text) -> None:
    frame = load_table(write_text("semi.csv", "a;b\n1;2\n"), delimiter=";")
    assert list(frame.columns) == ["a", "b"]


def test_corrupt_excel_raises(write_text) -> None:
    with pytest.raises(InputFileError, match="not a valid Excel workbook"):
        load_table(write_text("fake.xlsx", "this is not a workbook"))
