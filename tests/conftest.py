"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from data_cleaner.config import CleanerConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"


@pytest.fixture
def customer_config() -> CleanerConfig:
    """The real config used for the sample customer file."""
    return load_config(CONFIG_DIR / "customer_records.toml")


@pytest.fixture
def write_text(tmp_path: Path) -> Callable[..., Path]:
    """Write text to a file in a temporary folder and return its path."""

    def _write(name: str, content: str, encoding: str = "utf-8") -> Path:
        path = tmp_path / name
        path.write_text(content, encoding=encoding)
        return path

    return _write


@pytest.fixture
def raw_customers() -> pd.DataFrame:
    """A small messy table covering each cleaning rule, as loaded (all text)."""
    return pd.DataFrame(
        {
            " Customer ID": ["c-0001", "C-0002", "C-0003", "c-0001", "", "C-0005"],
            "Full Name": ["  zoë   müller ", "LIAM O'NEIL", "Ava Smith", "Zoë Müller", "", "Mia Lee"],
            "Email Address": [
                "Zoe.Muller@Example.com",
                "liam@example.com",
                "ava@example",
                " zoe.muller@example.com ",
                "",
                "mia@example.com",
            ],
            "Phone No.": ["(212) 555-0147", "+1 312 555 0101", "", "212.555.0147", "", "555-01"],
            "City ": ["new york", "N/A", "austin", "New York", "", "boston"],
            "Country": ["usa", "U.S.A.", "CANADA", "US", "", "us"],
            "SignupDate": ["2024-01-15", "03/07/2023", "Mar 09, 2022", "01/15/2024", "", "TBD"],
            "Total Spent ($)": ["$1,234.50", "USD 300", "(45.00)", "1234.5", "", "12"],
            "Membership": [" gold", "", "SILVER", "Gold", "", "bronze"],
        },
        dtype=object,
    )
