"""Tests for the cleaning pipeline (in-memory, no files)."""

from __future__ import annotations

import pandas as pd
import pytest

from data_cleaner.config import CleanerConfig, parse_config
from data_cleaner.exceptions import InputFileError, MissingColumnError
from data_cleaner.pipeline import REASON_COLUMN, ROW_COLUMN, CleaningResult, clean_dataframe


def _assert_rows_balance(result: CleaningResult) -> None:
    r = result.report
    assert r.rows_in == r.empty_rows_removed + r.rows_rejected + r.duplicates_removed + r.rows_out
    assert len(result.cleaned) == r.rows_out
    assert len(result.rejected) == r.rows_rejected + r.duplicates_removed


@pytest.fixture
def result(raw_customers: pd.DataFrame, customer_config: CleanerConfig) -> CleaningResult:
    return clean_dataframe(raw_customers, customer_config, input_name="customers.csv")


def test_row_accounting(result: CleaningResult) -> None:
    report = result.report
    assert (report.rows_in, report.empty_rows_removed) == (6, 1)
    assert (report.rows_rejected, report.duplicates_removed, report.rows_out) == (2, 1, 2)
    _assert_rows_balance(result)


def test_columns_are_standardized(result: CleaningResult) -> None:
    assert list(result.cleaned.columns) == [
        "customer_id",
        "full_name",
        "email_address",
        "phone_no",
        "city",
        "country",
        "signup_date",
        "total_spent",
        "membership",
    ]
    assert result.report.columns_renamed["Total Spent ($)"] == "total_spent"


def test_values_are_cleaned(result: CleaningResult) -> None:
    first, second = result.cleaned.to_dict("records")
    assert first["customer_id"] == "C-0001"
    assert first["full_name"] == "Zoë Müller"
    assert first["email_address"] == "zoe.muller@example.com"
    assert first["phone_no"] == "2125550147"
    assert first["city"] == "New York"
    assert first["country"] == "United States"
    assert first["signup_date"] == pd.Timestamp("2024-01-15")
    assert first["total_spent"] == pytest.approx(1234.5)
    assert first["membership"] == "Gold"

    assert second["full_name"] == "Liam O'Neil"
    assert second["phone_no"] == "3125550101"
    assert second["city"] == "Unknown"  # "N/A" -> missing -> filled
    assert second["membership"] == "Standard"
    assert second["signup_date"] == pd.Timestamp("2023-03-07")  # month-first config


def test_output_types(result: CleaningResult) -> None:
    assert pd.api.types.is_datetime64_any_dtype(result.cleaned["signup_date"])
    assert pd.api.types.is_float_dtype(result.cleaned["total_spent"])


def test_rejected_rows_keep_original_values_and_reasons(result: CleaningResult) -> None:
    rejected = result.rejected.set_index(ROW_COLUMN)
    assert list(rejected.index) == [4, 5, 7]  # spreadsheet row numbers, sorted
    assert rejected.at[4, "email_address"] == "ava@example"
    assert "Invalid email (email_address): 'ava@example'" in rejected.at[4, REASON_COLUMN]
    assert rejected.at[5, REASON_COLUMN] == "Duplicate of row 2"
    assert rejected.at[5, "email_address"] == " zoe.muller@example.com "  # untouched
    reason = rejected.at[7, REASON_COLUMN]
    assert "Invalid phone number (phone_no): '555-01'" in reason
    assert "Unrecognised date (signup_date): 'TBD'" in reason


def test_report_counts(result: CleaningResult) -> None:
    report = result.report
    assert report.rejection_reasons == {
        "Invalid email (email_address)": 1,
        "Invalid phone number (phone_no)": 1,
        "Unrecognised date (signup_date)": 1,
        "Duplicate record": 1,
    }
    assert report.stats_for("city").missing_filled == 1
    assert report.stats_for("membership").missing_filled == 1
    assert report.stats_for("email_address").invalid_values == 1
    assert report.stats_for("full_name").values_changed >= 2
    assert report.stats_for("total_spent").values_changed >= 1


def test_missing_value_strategies() -> None:
    raw = pd.DataFrame(
        {"id": ["1", "2", "3"], "a": ["x", "", "z"], "b": ["", "y", "n/a"], "c": ["", "", "q"]},
        dtype=object,
    )
    config = parse_config({"missing_values": {"a": "drop_row", "b": "fill:none given", "c": "leave"}})
    result = clean_dataframe(raw, config)
    assert result.cleaned["id"].tolist() == ["1", "3"]
    assert result.cleaned["b"].tolist() == ["none given", "none given"]
    assert result.cleaned["c"].isna().tolist() == [True, False]
    assert result.rejected[REASON_COLUMN].tolist() == ["Missing value (a)"]
    assert result.report.stats_for("c").missing_after_cleaning == 1


def test_required_column_missing_value_is_rejected() -> None:
    raw = pd.DataFrame({"email": ["a@x.com", "  "], "name": ["A", "B"]}, dtype=object)
    result = clean_dataframe(raw, parse_config({"columns": {"required": ["email"]}}))
    assert result.cleaned["name"].tolist() == ["A"]
    assert result.rejected[REASON_COLUMN].tolist() == ["Missing required value (email)"]


def test_config_column_not_in_input_raises() -> None:
    raw = pd.DataFrame({"name": ["A"]}, dtype=object)
    config = parse_config({"columns": {"required": ["email"]}})
    with pytest.raises(MissingColumnError, match="email.*Available columns: name"):
        clean_dataframe(raw, config)


def test_reserved_column_name_raises() -> None:
    raw = pd.DataFrame({"Source Row": ["1"], "name": ["A"]}, dtype=object)
    with pytest.raises(InputFileError, match="source_row"):
        clean_dataframe(raw, CleanerConfig())


def test_without_column_standardization() -> None:
    raw = pd.DataFrame({"E Mail": ["A@X.COM"]}, dtype=object)
    config = parse_config(
        {"general": {"standardize_column_names": False}, "columns": {"emails": ["E Mail"]}}
    )
    result = clean_dataframe(raw, config)
    assert result.cleaned.to_dict("records") == [{"E Mail": "a@x.com"}]
    assert result.report.columns_renamed == {}


def test_all_duplicates_file() -> None:
    raw = pd.DataFrame({"a": ["1"] * 5, "b": ["x"] * 5}, dtype=object)
    result = clean_dataframe(raw, CleanerConfig())
    assert len(result.cleaned) == 1
    assert result.report.duplicates_removed == 4
    assert set(result.rejected[REASON_COLUMN]) == {"Duplicate of row 2"}
    _assert_rows_balance(result)


def test_single_row() -> None:
    result = clean_dataframe(pd.DataFrame({"a": [" hi "]}, dtype=object), CleanerConfig())
    assert result.cleaned["a"].tolist() == ["hi"]
    assert result.rejected.empty
    assert list(result.rejected.columns) == [ROW_COLUMN, REASON_COLUMN, "a"]


def test_every_row_rejected(customer_config: CleanerConfig, raw_customers: pd.DataFrame) -> None:
    raw = raw_customers.copy()
    raw["Email Address"] = "not-an-email"
    result = clean_dataframe(raw, customer_config)
    assert result.cleaned.empty
    assert list(result.cleaned.columns)[0] == "customer_id"
    _assert_rows_balance(result)


def test_numbers_with_missing_values_and_fill() -> None:
    raw = pd.DataFrame({"qty": ["2", "", "1,000"], "id": ["a", "b", "c"]}, dtype=object)
    config = parse_config({"columns": {"numbers": ["qty"]}, "missing_values": {"qty": "fill:0"}})
    result = clean_dataframe(raw, config)
    assert result.cleaned["qty"].tolist() == [2, 0, 1000]
    assert str(result.cleaned["qty"].dtype) == "Int64"


def test_input_frame_is_not_modified(raw_customers: pd.DataFrame, customer_config) -> None:
    before = raw_customers.copy()
    clean_dataframe(raw_customers, customer_config)
    pd.testing.assert_frame_equal(raw_customers, before)
