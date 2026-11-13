"""Tests for configuration loading and validation."""

from __future__ import annotations

from typing import Any

import pytest

from data_cleaner.config import DEFAULT_DATE_FORMATS, CleanerConfig, load_config, parse_config
from data_cleaner.exceptions import ConfigError
from tests.conftest import CONFIG_DIR


def test_no_path_returns_defaults() -> None:
    config = load_config(None)
    assert config == CleanerConfig()
    assert config.date_formats == DEFAULT_DATE_FORMATS
    assert config.duplicate_subset == ()


def test_loads_customer_config() -> None:
    config = load_config(CONFIG_DIR / "customer_records.toml")
    assert config.required_columns == ("customer_id", "full_name", "email_address")
    assert config.email_columns == ("email_address",)
    assert config.text_case["full_name"] == "title"
    assert config.value_maps["country"]["u.s.a."] == "United States"
    assert config.missing_values["city"] == "fill:Unknown"
    assert config.phone_country_code == "1"


def test_loads_sales_config() -> None:
    config = load_config(CONFIG_DIR / "sales_orders.toml")
    assert config.number_columns == ("quantity", "unit_price_inr")
    assert config.excel_date_format == "dd-mmm-yyyy"


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_malformed_toml_raises(write_text) -> None:
    path = write_text("bad.toml", "[columns\nrequired = [")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(path)


def test_empty_file_gives_defaults(write_text) -> None:
    assert load_config(write_text("empty.toml", "")) == CleanerConfig()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"colums": {}}, "Unknown config section"),
        ({"columns": {"emial": ["x"]}}, "Unknown key"),
        ({"columns": "email"}, "must be a table"),
        ({"columns": {"required": "email"}}, "list of strings"),
        ({"columns": {"required": [1, 2]}}, "list of strings"),
        ({"text_case": {"name": "camel"}}, "is invalid"),
        ({"missing_values": {"city": "remove"}}, "is invalid"),
        ({"missing_values": {"city": "fill:"}}, "is invalid"),
        ({"value_maps": {"country": "USA"}}, "must map text values"),
        ({"phones": {"digits": 0}}, "positive whole number"),
        ({"phones": {"digits": True}}, "positive whole number"),
        ({"phones": {"country_code": "+1"}}, "string of digits"),
        ({"general": {"standardize_column_names": "yes"}}, "true or false"),
        ({"dates": {"formats": []}}, "at least one format"),
        ({"columns": {"emails": ["contact"], "phones": ["contact"]}}, "listed in both"),
    ],
)
def test_invalid_rules_raise(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config(data)


def test_value_map_keys_are_normalized() -> None:
    config = parse_config({"value_maps": {"country": {"  U.S.A. ": "United States"}}})
    assert config.value_maps["country"] == {"u.s.a.": "United States"}


def test_missing_markers_are_lowercased() -> None:
    config = parse_config({"general": {"missing_markers": [" N/A ", "NULL"]}})
    assert config.missing_markers == ("n/a", "null")


def test_referenced_columns_and_override() -> None:
    config = parse_config(
        {"columns": {"required": ["a"], "dates": ["b"]}, "duplicates": {"subset": ["c"]}}
    )
    assert config.referenced_columns() == {"a", "b", "c"}
    assert config.with_duplicate_subset(("a",)).duplicate_subset == ("a",)
    assert config.duplicate_subset == ("c",)  # original unchanged (immutable)
