"""Pure cleaning functions.

Value-level functions (``clean_text_value``, ``parse_number``, ``parse_date`` ...)
work on a single cell and are easy to unit-test. Series-level helpers apply them
to a whole column and return both the cleaned values and a mask of values that
could not be converted, so the pipeline can report them instead of silently
dropping data.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from datetime import datetime

import pandas as pd

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALPHANUMERIC = re.compile(r"[^0-9a-z]+")
_CURRENCY = re.compile(r"[$€£¥₹]|\b(?:USD|EUR|GBP|INR|Rs\.?)(?=[\s\d.(-]|$)", re.IGNORECASE)
_TITLE_APOSTROPHE_S = re.compile(r"'S\b")


# --------------------------------------------------------------------------- column names


def to_snake_case(name: str) -> str:
    """Convert a header such as ``" Signup Date "`` or ``"CustomerID"`` to snake_case.

    >>> to_snake_case("Total Spent ($)")
    'total_spent'
    """
    spaced = _CAMEL_BOUNDARY.sub("_", str(name).strip())
    return _NON_ALPHANUMERIC.sub("_", spaced.lower()).strip("_")


def standardize_column_names(columns: Sequence[str]) -> list[str]:
    """Return snake_case column names, guaranteed non-empty and unique.

    Blank headers become ``column_<position>``; repeated names get a numeric
    suffix (``amount``, ``amount_2``) so no column is lost.
    """
    result: list[str] = []
    used: set[str] = set()
    for position, name in enumerate(columns, start=1):
        base = to_snake_case(name) or f"column_{position}"
        candidate, suffix = base, 2
        while candidate in used:
            candidate, suffix = f"{base}_{suffix}", suffix + 1
        used.add(candidate)
        result.append(candidate)
    return result


# --------------------------------------------------------------------------- text


def clean_text_value(value: object, missing_markers: Iterable[str]) -> str | None:
    """Trim and collapse whitespace; return None for blanks and missing markers.

    ``missing_markers`` are compared case-insensitively, so ``"N/A"``, ``"n/a"``
    and ``"NULL"`` are all treated as missing.
    """
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = " ".join(str(value).split())  # also removes tabs, newlines, non-breaking spaces
    if not text or text.lower() in missing_markers:
        return None
    return text


def clean_text(series: pd.Series, missing_markers: Iterable[str]) -> pd.Series:
    """Apply :func:`clean_text_value` to every value in a column."""
    markers = frozenset(marker.lower() for marker in missing_markers)
    return series.map(lambda value: clean_text_value(value, markers)).astype(object)


def apply_case(value: str, case: str, acronyms: Iterable[str] = ()) -> str:
    """Change the letter case of a text value.

    ``case`` is one of ``title`` ("Mary O'Neil"), ``lower``, ``upper`` or
    ``sentence`` ("Hello world"). For title and sentence case, words listed in
    ``acronyms`` keep their capitals ("hd webcam" -> "HD Webcam").
    """
    if case == "title":
        # str.title() turns "it's" into "It'S"; fix that common artefact.
        result = _TITLE_APOSTROPHE_S.sub("'s", value.title())
    elif case == "sentence":
        result = value[:1].upper() + value[1:].lower()
    elif case == "lower":
        return value.lower()
    elif case == "upper":
        return value.upper()
    else:
        raise ValueError(f"Unknown case: {case!r}")
    return _restore_acronyms(result, acronyms)


def _restore_acronyms(text: str, acronyms: Iterable[str]) -> str:
    lookup = {acronym.upper(): acronym for acronym in acronyms}
    if not lookup:
        return text
    return " ".join(lookup.get(word.upper(), word) for word in text.split(" "))


def apply_value_map(value: str, mapping: dict[str, str]) -> str:
    """Replace a value using a case-insensitive lookup (e.g. ``"usa"`` -> ``"United States"``)."""
    return mapping.get(value.lower(), value)


# --------------------------------------------------------------------------- numbers


def parse_number(value: str) -> float | None:
    """Parse text such as ``"$1,234.50"``, ``"USD 300"`` or ``"(45.00)"`` into a float.

    Currency symbols/codes, thousands separators and spaces are removed;
    accounting-style parentheses mean a negative number. Returns None when the
    text is not a number.
    """
    text = _CURRENCY.sub("", value).replace(",", "").replace(" ", "").strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):  # float() accepts "nan" and "inf"
        return None
    return -number if negative else number


def convert_numbers(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Convert a text column to numbers.

    Returns:
        ``(numbers, invalid_mask)`` where ``invalid_mask`` is True for values
        that were present but could not be parsed.
    """
    parsed = series.map(lambda value: None if pd.isna(value) else parse_number(str(value)))
    numbers = pd.to_numeric(parsed, errors="coerce").astype("float64")
    invalid = series.notna() & numbers.isna()
    return _to_integer_if_whole(numbers), invalid


def _to_integer_if_whole(numbers: pd.Series) -> pd.Series:
    """Use a nullable integer type when every value is a whole number (e.g. quantities)."""
    present = numbers.dropna()
    if not present.empty and (present % 1 == 0).all():
        return numbers.astype("Int64")
    return numbers


# --------------------------------------------------------------------------- dates


def parse_date(value: str, formats: Sequence[str]) -> datetime | None:
    """Parse a date using the first matching ``strptime`` format, or return None."""
    text = value.strip()
    for date_format in formats:
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def convert_dates(series: pd.Series, formats: Sequence[str]) -> tuple[pd.Series, pd.Series]:
    """Convert a text column with mixed date formats to real dates.

    Returns:
        ``(dates, invalid_mask)`` - see :func:`convert_numbers`.
    """
    parsed = series.map(lambda value: None if pd.isna(value) else parse_date(str(value), formats))
    dates = pd.to_datetime(parsed, errors="coerce")
    invalid = series.notna() & dates.isna()
    return dates, invalid


# --------------------------------------------------------------------------- duplicates


def find_duplicates(frame: pd.DataFrame, subset: Sequence[str], row_column: str) -> pd.Series:
    """Identify duplicate rows, keeping the first occurrence.

    Args:
        frame: Cleaned data.
        subset: Columns that identify a record (e.g. ``["email"]``). An empty
            subset compares every column except ``row_column``.
        row_column: Column holding the original row number.

    Returns:
        A Series aligned with ``frame``: for each duplicate, the original row
        number of the record it duplicates; missing for non-duplicates.
        With an explicit subset, rows whose key is blank are never treated as
        duplicates (two customers without an email are not the same person).
    """
    keys = list(subset) or [column for column in frame.columns if column != row_column]
    is_duplicate = frame.duplicated(subset=keys, keep="first")
    if subset:
        is_duplicate &= frame[keys].notna().all(axis=1)
    first_row = frame.groupby(keys, dropna=False, sort=False)[row_column].transform("first")
    return first_row.where(is_duplicate)
