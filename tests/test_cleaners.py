"""Tests for the pure cleaning functions."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from data_cleaner.cleaners import (
    apply_case,
    apply_value_map,
    clean_text,
    clean_text_value,
    convert_dates,
    convert_numbers,
    find_duplicates,
    parse_date,
    parse_number,
    standardize_column_names,
    to_snake_case,
)
from data_cleaner.config import DEFAULT_MISSING_MARKERS

MARKERS = frozenset(DEFAULT_MISSING_MARKERS)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (" Customer ID", "customer_id"),
        ("Total Spent ($)", "total_spent"),
        ("SignupDate", "signup_date"),
        ("Phone No.", "phone_no"),
        ("e-mail", "e_mail"),
        ("ALREADY_SNAKE", "already_snake"),
        ("   ", ""),
    ],
)
def test_to_snake_case(header: str, expected: str) -> None:
    assert to_snake_case(header) == expected


def test_standardize_column_names_handles_blanks_and_duplicates() -> None:
    assert standardize_column_names(["Amount", "amount ", "", "Amount"]) == [
        "amount",
        "amount_2",
        "column_3",
        "amount_3",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  John   Smith ", "John Smith"),
        ("\tNew\nYork City", "New York City"),
        ("N/A", None),
        ("null", None),
        (" - ", None),
        ("", None),
        ("   ", None),
        (None, None),
        (float("nan"), None),
        (42, "42"),
        ("Nancy", "Nancy"),  # "na" is a marker, but only as the whole value
    ],
)
def test_clean_text_value(value: object, expected: str | None) -> None:
    assert clean_text_value(value, MARKERS) == expected


def test_clean_text_empty_series() -> None:
    assert clean_text(pd.Series([], dtype=object), MARKERS).empty


@pytest.mark.parametrize(
    ("value", "case", "expected"),
    [
        ("liam o'neil", "title", "Liam O'Neil"),
        ("it's mary-jane", "title", "It's Mary-Jane"),
        ("zoë müller", "title", "Zoë Müller"),
        ("MiXeD", "lower", "mixed"),
        ("c-0001", "upper", "C-0001"),
        ("hELLO wORLD", "sentence", "Hello world"),
    ],
)
def test_apply_case(value: str, case: str, expected: str) -> None:
    assert apply_case(value, case) == expected


def test_apply_case_keeps_acronyms() -> None:
    acronyms = ("HD", "USB-C")
    assert apply_case("HD WEBCAM", "title", acronyms) == "HD Webcam"
    assert apply_case("usb-c cable", "title", acronyms) == "USB-C Cable"
    assert apply_case("hd webcam", "sentence", acronyms) == "HD webcam"
    assert apply_case("hd webcam", "lower", acronyms) == "hd webcam"  # explicit lower wins


def test_apply_case_rejects_unknown_case() -> None:
    with pytest.raises(ValueError, match="Unknown case"):
        apply_case("x", "camel")


def test_apply_value_map_is_case_insensitive() -> None:
    mapping = {"usa": "United States"}
    assert apply_value_map("USA", mapping) == "United States"
    assert apply_value_map("Canada", mapping) == "Canada"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1234.5", 1234.5),
        ("$1,234.50", 1234.5),
        ("USD 300", 300.0),
        ("300 usd", 300.0),
        ("₹1,499.00", 1499.0),
        ("Rs. 799", 799.0),
        ("(45.00)", -45.0),
        ("-12", -12.0),
        (" 1 234 ", 1234.0),
        ("abc", None),
        ("12..5", None),
        ("nan", None),
        ("inf", None),
        ("", None),
    ],
)
def test_parse_number(text: str, expected: float | None) -> None:
    assert parse_number(text) == expected


def test_convert_numbers_marks_invalid_but_not_missing() -> None:
    numbers, invalid = convert_numbers(pd.Series(["$10.50", None, "oops", "2"], dtype=object))
    assert numbers.iloc[0] == 10.5
    assert pd.isna(numbers.iloc[1]) and pd.isna(numbers.iloc[2])
    assert invalid.tolist() == [False, False, True, False]


def test_convert_numbers_uses_integers_for_whole_numbers() -> None:
    numbers, _ = convert_numbers(pd.Series(["1", " 2 ", None], dtype=object))
    assert str(numbers.dtype) == "Int64"
    assert numbers.tolist()[:2] == [1, 2]


FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%d %b %Y")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024-01-15", datetime(2024, 1, 15)),
        ("01/15/2024", datetime(2024, 1, 15)),
        ("Jan 15, 2024", datetime(2024, 1, 15)),
        (" 15 Jan 2024 ", datetime(2024, 1, 15)),
        ("2023-02-30", None),  # impossible date
        ("13/45/2023", None),
        ("TBD", None),
    ],
)
def test_parse_date(text: str, expected: datetime | None) -> None:
    assert parse_date(text, FORMATS) == expected


def test_first_matching_format_wins_for_ambiguous_dates() -> None:
    assert parse_date("03/04/2024", ("%d/%m/%Y", "%m/%d/%Y")) == datetime(2024, 4, 3)
    assert parse_date("03/04/2024", ("%m/%d/%Y", "%d/%m/%Y")) == datetime(2024, 3, 4)


def test_convert_dates_handles_mixed_formats() -> None:
    series = pd.Series(["2024-01-15", "Jan 16, 2024", None, "someday"], dtype=object)
    dates, invalid = convert_dates(series, FORMATS)
    assert dates.iloc[0] == pd.Timestamp("2024-01-15")
    assert dates.iloc[1] == pd.Timestamp("2024-01-16")
    assert invalid.tolist() == [False, False, False, True]


def test_convert_dates_all_missing() -> None:
    dates, invalid = convert_dates(pd.Series([None, None], dtype=object), FORMATS)
    assert dates.isna().all()
    assert not invalid.any()


def _frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, dtype=object)
    frame.insert(0, "source_row", range(2, len(frame) + 2))
    return frame


def test_find_duplicates_on_key_columns() -> None:
    frame = _frame(
        [
            {"email": "a@x.com", "name": "A"},
            {"email": "b@x.com", "name": "B"},
            {"email": "a@x.com", "name": "A. N. Other"},
        ]
    )
    result = find_duplicates(frame, ["email"], "source_row")
    assert pd.isna(result.iloc[0]) and pd.isna(result.iloc[1])
    assert result.iloc[2] == 2  # duplicate of spreadsheet row 2


def test_find_duplicates_full_row_ignores_row_number() -> None:
    frame = _frame([{"a": "1", "b": "x"}, {"a": "1", "b": "x"}, {"a": "1", "b": "y"}])
    assert find_duplicates(frame, [], "source_row").notna().tolist() == [False, True, False]


def test_blank_keys_are_not_duplicates() -> None:
    frame = _frame([{"email": None, "name": "A"}, {"email": None, "name": "B"}])
    assert find_duplicates(frame, ["email"], "source_row").isna().all()


def test_all_rows_identical() -> None:
    frame = _frame([{"a": "same"}] * 4)
    assert find_duplicates(frame, [], "source_row").notna().sum() == 3
