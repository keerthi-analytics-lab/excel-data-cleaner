"""Load and validate cleaning rules from a TOML configuration file.

All cleaning behaviour is driven by a :class:`CleanerConfig` object, so the same
code can clean a customer list, a sales export, or any other table just by
pointing it at a different config file. TOML is parsed with the standard-library
``tomllib`` module, so no extra dependency is needed.

Column names in the config refer to the *standardized* names (``snake_case``),
for example ``"Signup Date"`` in the input file becomes ``signup_date``.
"""

from __future__ import annotations

import dataclasses
import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from data_cleaner.exceptions import ConfigError

logger = logging.getLogger(__name__)

VALID_CASES: frozenset[str] = frozenset({"title", "lower", "upper", "sentence"})
MISSING_LEAVE = "leave"
MISSING_DROP_ROW = "drop_row"
FILL_PREFIX = "fill:"

DEFAULT_MISSING_MARKERS: tuple[str, ...] = ("", "na", "n/a", "null", "none", "nan", "-", "?")

# The first format that matches a value wins, so order matters for ambiguous
# dates such as 03/04/2024 (day-first here; override in the config for US data).
DEFAULT_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d %b %Y",
    "%d-%b-%Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
)

# Allowed sections and keys; anything else is reported as a likely typo.
_ALLOWED_KEYS: dict[str, set[str]] = {
    "general": {"standardize_column_names", "missing_markers", "acronyms"},
    "columns": {"required", "emails", "phones", "dates", "numbers"},
    "text_case": set(),  # free-form: column -> case
    "value_maps": set(),  # free-form: column -> {old: new}
    "missing_values": set(),  # free-form: column -> strategy
    "duplicates": {"subset"},
    "dates": {"formats"},
    "phones": {"digits", "country_code"},
    "excel": {"date_format", "number_format"},
}


@dataclass(frozen=True)
class CleanerConfig:
    """Validated cleaning rules.

    The defaults give a sensible generic clean (tidy column names, trim
    whitespace, recognise common "missing" markers, remove exact duplicate
    rows) so the tool is useful even without a config file.
    """

    standardize_column_names: bool = True
    missing_markers: tuple[str, ...] = DEFAULT_MISSING_MARKERS
    acronyms: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()
    email_columns: tuple[str, ...] = ()
    phone_columns: tuple[str, ...] = ()
    date_columns: tuple[str, ...] = ()
    number_columns: tuple[str, ...] = ()
    text_case: dict[str, str] = field(default_factory=dict)
    value_maps: dict[str, dict[str, str]] = field(default_factory=dict)
    missing_values: dict[str, str] = field(default_factory=dict)
    duplicate_subset: tuple[str, ...] = ()
    date_formats: tuple[str, ...] = DEFAULT_DATE_FORMATS
    phone_digits: int = 10
    phone_country_code: str = ""
    excel_date_format: str = "yyyy-mm-dd"
    excel_number_format: str = "#,##0.00"

    def referenced_columns(self) -> set[str]:
        """Return every column name mentioned anywhere in the rules."""
        return {
            *self.required_columns,
            *self.email_columns,
            *self.phone_columns,
            *self.date_columns,
            *self.number_columns,
            *self.text_case,
            *self.value_maps,
            *self.missing_values,
            *self.duplicate_subset,
        }

    def with_duplicate_subset(self, subset: tuple[str, ...]) -> CleanerConfig:
        """Return a copy with a different duplicate key (used by CLI overrides)."""
        return dataclasses.replace(self, duplicate_subset=subset)


def load_config(path: str | Path | None) -> CleanerConfig:
    """Load a TOML config file, or return the built-in defaults if ``path`` is None.

    Raises:
        ConfigError: if the file is missing, is not valid TOML, or contains
            invalid rules.
    """
    if path is None:
        logger.info("No config file given - using built-in default rules")
        return CleanerConfig()

    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config file {config_path} is not valid TOML: {exc}") from exc

    config = parse_config(data)
    logger.info("Loaded config from %s", config_path)
    return config


def parse_config(data: dict[str, Any]) -> CleanerConfig:
    """Build a :class:`CleanerConfig` from an already-parsed TOML dictionary."""
    unknown_sections = set(data) - set(_ALLOWED_KEYS)
    if unknown_sections:
        raise ConfigError(f"Unknown config section(s): {', '.join(sorted(unknown_sections))}")

    general = _table(data, "general")
    columns = _table(data, "columns")
    duplicates = _table(data, "duplicates")
    dates = _table(data, "dates")
    phones = _table(data, "phones")
    excel = _table(data, "excel")

    standardize = general.get("standardize_column_names", True)
    if not isinstance(standardize, bool):
        raise ConfigError("[general] standardize_column_names must be true or false")

    markers = general.get("missing_markers")
    missing_markers = (
        DEFAULT_MISSING_MARKERS
        if markers is None
        else tuple(m.strip().lower() for m in _string_list(markers, "[general] missing_markers"))
    )

    date_formats = dates.get("formats")
    phone_digits = phones.get("digits", 10)
    if not isinstance(phone_digits, int) or isinstance(phone_digits, bool) or phone_digits <= 0:
        raise ConfigError("[phones] digits must be a positive whole number")
    country_code = phones.get("country_code", "")
    if not isinstance(country_code, str) or (country_code and not country_code.isdigit()):
        raise ConfigError('[phones] country_code must be a string of digits, e.g. "1" or "91"')

    config = CleanerConfig(
        standardize_column_names=standardize,
        missing_markers=missing_markers,
        acronyms=_string_list(general.get("acronyms", []), "[general] acronyms"),
        required_columns=_string_list(columns.get("required", []), "[columns] required"),
        email_columns=_string_list(columns.get("emails", []), "[columns] emails"),
        phone_columns=_string_list(columns.get("phones", []), "[columns] phones"),
        date_columns=_string_list(columns.get("dates", []), "[columns] dates"),
        number_columns=_string_list(columns.get("numbers", []), "[columns] numbers"),
        text_case=_parse_text_case(_table(data, "text_case")),
        value_maps=_parse_value_maps(_table(data, "value_maps")),
        missing_values=_parse_missing_values(_table(data, "missing_values")),
        duplicate_subset=_string_list(duplicates.get("subset", []), "[duplicates] subset"),
        date_formats=(
            DEFAULT_DATE_FORMATS
            if date_formats is None
            else _string_list(date_formats, "[dates] formats")
        ),
        phone_digits=phone_digits,
        phone_country_code=country_code,
        excel_date_format=_string(excel.get("date_format", "yyyy-mm-dd"), "[excel] date_format"),
        excel_number_format=_string(
            excel.get("number_format", "#,##0.00"), "[excel] number_format"
        ),
    )
    _check_typed_columns_do_not_overlap(config)
    if not config.date_formats:
        raise ConfigError("[dates] formats must contain at least one format")
    return config


# --------------------------------------------------------------------------- helpers


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a config section as a dict, checking its type and allowed keys."""
    table = data.get(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"[{name}] must be a table/section")
    allowed = _ALLOWED_KEYS[name]
    if allowed:
        unknown = set(table) - allowed
        if unknown:
            raise ConfigError(f"Unknown key(s) in [{name}]: {', '.join(sorted(unknown))}")
    return table


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} must be a non-empty string")
    return value


def _string_list(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{where} must be a list of strings")
    return tuple(value)


def _parse_text_case(table: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for column, case in table.items():
        if not isinstance(case, str) or case.lower() not in VALID_CASES:
            raise ConfigError(
                f"[text_case] {column} = {case!r} is invalid; "
                f"use one of: {', '.join(sorted(VALID_CASES))}"
            )
        result[column] = case.lower()
    return result


def _parse_value_maps(table: dict[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for column, mapping in table.items():
        if not isinstance(mapping, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
        ):
            raise ConfigError(f"[value_maps.{column}] must map text values to text values")
        # Keys are matched case-insensitively after whitespace cleaning.
        result[column] = {" ".join(k.split()).lower(): v for k, v in mapping.items()}
    return result


def _parse_missing_values(table: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for column, strategy in table.items():
        valid = isinstance(strategy, str) and (
            strategy in (MISSING_LEAVE, MISSING_DROP_ROW)
            or (strategy.startswith(FILL_PREFIX) and len(strategy) > len(FILL_PREFIX))
        )
        if not valid:
            raise ConfigError(
                f"[missing_values] {column} = {strategy!r} is invalid; "
                f'use "leave", "drop_row" or "fill:<value>"'
            )
        result[column] = strategy
    return result


def _check_typed_columns_do_not_overlap(config: CleanerConfig) -> None:
    """A column can be an email, phone, date or number column - not several."""
    seen: dict[str, str] = {}
    for kind, names in (
        ("emails", config.email_columns),
        ("phones", config.phone_columns),
        ("dates", config.date_columns),
        ("numbers", config.number_columns),
    ):
        for name in names:
            if name in seen:
                raise ConfigError(
                    f"Column '{name}' is listed in both [columns] {seen[name]} and {kind}"
                )
            seen[name] = kind
