"""Tests for email, phone and column validation."""

from __future__ import annotations

import pytest

from data_cleaner.validators import find_missing_columns, is_valid_email, normalize_phone


@pytest.mark.parametrize(
    "email",
    ["ava@example.com", "first.last+tag@example.co.uk", "o_neil-99@sub.example.org"],
)
def test_valid_emails(email: str) -> None:
    assert is_valid_email(email)


@pytest.mark.parametrize(
    "email",
    [
        "ava.example.com",
        "ava@",
        "ava@@example.com",
        "ava@example",
        "ava @example.com",
        "ava..b@example.com",
        ".ava@example.com",
        "ava.@example.com",
        "@example.com",
        "",
    ],
)
def test_invalid_emails(email: str) -> None:
    assert not is_valid_email(email)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(212) 555-0147", "2125550147"),
        ("212.555.0147", "2125550147"),
        ("+1 212 555 0147", "2125550147"),
        ("1-212-555-0147", "2125550147"),
        ("02125550147", "2125550147"),  # trunk prefix 0
        ("555-0147", None),  # too short
        ("212-555-01478", None),  # too long
        ("call me", None),
    ],
)
def test_normalize_phone(raw: str, expected: str | None) -> None:
    assert normalize_phone(raw, digits=10, country_code="1") == expected


def test_normalize_phone_other_country() -> None:
    assert normalize_phone("+91 98765 43210", digits=10, country_code="91") == "9876543210"
    assert normalize_phone("+91 98765 43210", digits=10) is None  # code not configured


def test_find_missing_columns() -> None:
    assert find_missing_columns(["b", "a", "c"], ["c", "x"]) == ["a", "b"]
    assert find_missing_columns([], ["x"]) == []
