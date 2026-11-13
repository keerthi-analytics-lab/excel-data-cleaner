"""Validation rules for emails, phone numbers and required columns."""

from __future__ import annotations

import re
from collections.abc import Iterable

# Practical email check: something@domain.tld. Deliberately simpler than the
# full RFC 5322 grammar, which accepts addresses no real CRM would.
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
_NON_DIGIT = re.compile(r"\D")


def is_valid_email(value: str) -> bool:
    """Return True if ``value`` looks like a usable email address."""
    if ".." in value or value.startswith(".") or ".@" in value:
        return False
    return EMAIL_PATTERN.fullmatch(value) is not None


def normalize_phone(value: str, digits: int, country_code: str = "") -> str | None:
    """Reduce a phone number to its national digits, or return None if invalid.

    ``"+1 (212) 555-0147"`` and ``"212.555.0147"`` both become ``"2125550147"``
    when ``digits=10`` and ``country_code="1"``. A leading country code or a
    single trunk ``0`` is removed; any other length is invalid.

    Args:
        value: Phone number as typed.
        digits: Expected number of national digits.
        country_code: Optional country calling code to strip (digits only).
    """
    only_digits = _NON_DIGIT.sub("", value)
    if (
        country_code
        and len(only_digits) == digits + len(country_code)
        and only_digits.startswith(country_code)
    ):
        only_digits = only_digits[len(country_code) :]
    elif len(only_digits) == digits + 1 and only_digits.startswith("0"):
        only_digits = only_digits[1:]
    return only_digits if len(only_digits) == digits else None


def find_missing_columns(expected: Iterable[str], available: Iterable[str]) -> list[str]:
    """Return the expected column names that are not available, sorted."""
    return sorted(set(expected) - set(available))
