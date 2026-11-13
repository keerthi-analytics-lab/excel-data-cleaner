"""End-to-end tests: run the command-line tool on real files."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from openpyxl import load_workbook

from data_cleaner.cli import (
    EXIT_ERROR,
    EXIT_OK,
    default_output_path,
    main,
    parse_column_list,
)
from data_cleaner.exporter import SHEET_CLEANED, SHEET_REJECTED
from tests.conftest import CONFIG_DIR, SAMPLE_DIR

CUSTOMERS_CSV = SAMPLE_DIR / "raw_customer_records.csv"
SALES_XLSX = SAMPLE_DIR / "raw_sales_orders.xlsx"


@pytest.fixture(autouse=True)
def _reset_logging():
    """Close the handlers main() installs so temp log files can be deleted."""
    yield
    logger = logging.getLogger("data_cleaner")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _data_rows(path: Path, sheet: str) -> int:
    return load_workbook(path)[sheet].max_row - 1


def test_cleans_sample_customer_file(tmp_path: Path) -> None:
    output = tmp_path / "customers.xlsx"
    log_file = tmp_path / "logs" / "run.log"
    code = main(
        [
            str(CUSTOMERS_CSV),
            "-c",
            str(CONFIG_DIR / "customer_records.toml"),
            "-o",
            str(output),
            "--log-file",
            str(log_file),
            "--verbose",
        ]
    )
    assert code == EXIT_OK
    clean_rows = _data_rows(output, SHEET_CLEANED)
    rejected_rows = _data_rows(output, SHEET_REJECTED)
    assert clean_rows > 100
    assert rejected_rows >= 20  # invalid values, missing required fields and duplicates
    log_text = log_file.read_text(encoding="utf-8")
    assert "Cleaning summary" in log_text
    assert "removed: Duplicate of row" in log_text  # DEBUG detail goes to the file


def test_cleans_sample_sales_workbook(tmp_path: Path) -> None:
    output = tmp_path / "sales.xlsx"
    code = main(
        [
            str(SALES_XLSX),
            "-c",
            str(CONFIG_DIR / "sales_orders.toml"),
            "--sheet",
            "Orders",
            "-o",
            str(output),
            "--no-log-file",
        ]
    )
    assert code == EXIT_OK
    sheet = load_workbook(output)[SHEET_CLEANED]
    headers = [cell.value for cell in sheet[1]]
    regions = {row[headers.index("region")] for row in sheet.iter_rows(min_row=2, values_only=True)}
    assert regions <= {"North", "South", "East", "West", "Unassigned"}
    products = {row[headers.index("product")] for row in sheet.iter_rows(min_row=2, values_only=True)}
    assert {"HD Webcam", "USB-C Cable"} <= products


def test_runs_without_config(tmp_path: Path, write_text) -> None:
    source = write_text("plain.csv", "Name ,City\n Ann ,Pune\nAnn,Pune\n")
    output = tmp_path / "plain.xlsx"
    assert main([str(source), "-o", str(output), "--no-log-file"]) == EXIT_OK
    assert _data_rows(output, SHEET_CLEANED) == 1  # exact duplicate removed


def test_dedupe_override(tmp_path: Path, write_text) -> None:
    source = write_text("people.csv", "name,city\nAnn,Pune\nAnn,Delhi\n")
    output = tmp_path / "people.xlsx"
    assert main([str(source), "-o", str(output), "--dedupe-on", "name", "--no-log-file"]) == 0
    assert _data_rows(output, SHEET_CLEANED) == 1


@pytest.mark.parametrize(
    ("make_args", "message"),
    [
        (lambda tmp, write: [str(tmp / "missing.csv")], "not found"),
        (lambda tmp, write: [str(write("empty.csv", ""))], "empty"),
        (lambda tmp, write: [str(write("notes.txt", "a\n1\n"))], "Unsupported file type"),
        (
            lambda tmp, write: [str(write("ok.csv", "a\n1\n")), "-c", str(write("bad.toml", "[x"))],
            "not valid TOML",
        ),
        (
            lambda tmp, write: [str(write("ok.csv", "a\n1\n")), "--dedupe-on", "email"],
            "not found in the input: email",
        ),
        (
            lambda tmp, write: [str(write("ok.csv", "a\n1\n")), "-o", str(tmp / "out.csv")],
            ".xlsx extension",
        ),
    ],
)
def test_errors_exit_with_message(make_args, message, tmp_path, write_text, capsys) -> None:
    args = make_args(tmp_path, write_text) + ["--no-log-file"]
    assert main(args) == EXIT_ERROR
    assert message in capsys.readouterr().err


def test_bad_argument_exits_with_usage_error(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_helpers() -> None:
    assert default_output_path(Path("data/customers.csv")) == Path("output/customers_cleaned.xlsx")
    assert parse_column_list(" email, phone ,,") == ("email", "phone")
