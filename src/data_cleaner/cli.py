"""Command-line interface.

Examples::

    python -m data_cleaner data/sample/raw_customer_records.csv -c config/customer_records.toml
    python -m data_cleaner orders.xlsx --sheet "Jan 2026" --dedupe-on order_id -o clean.xlsx
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from data_cleaner import __version__
from data_cleaner.config import load_config
from data_cleaner.exceptions import DataCleanerError
from data_cleaner.logging_setup import configure_logging
from data_cleaner.pipeline import run_pipeline

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1  # expected problem: bad input file, bad config, ...
EXIT_UNEXPECTED = 3  # bug - full traceback goes to the log file
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_LOG_FILE = Path("logs") / "cleaner.log"


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="data-cleaner",
        description=(
            "Clean a messy CSV or Excel file and export a formatted Excel workbook "
            "with Cleaned Data, Rejected Rows and Cleaning Summary sheets."
        ),
        epilog=(
            "example: python -m data_cleaner data/sample/raw_customer_records.csv "
            "-c config/customer_records.toml"
        ),
    )
    parser.add_argument("input", type=Path, help="CSV (.csv) or Excel (.xlsx/.xlsm) file to clean")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output .xlsx path (default: output/<input name>_cleaned.xlsx)",
    )
    parser.add_argument(
        "-c", "--config", type=Path, help="TOML file with cleaning rules (default: generic rules)"
    )
    parser.add_argument("--sheet", help="worksheet to read from an Excel file (default: first)")
    parser.add_argument(
        "--delimiter", default=",", help=r"CSV field separator, e.g. ';' or '\t' (default: ',')"
    )
    parser.add_argument(
        "--dedupe-on",
        metavar="COLUMNS",
        help="comma-separated columns that identify a duplicate record (overrides the config)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=DEFAULT_LOG_FILE,
        help=f"detailed log file (default: {DEFAULT_LOG_FILE.as_posix()})",
    )
    parser.add_argument("--no-log-file", action="store_true", help="do not write a log file")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show debug details, e.g. each rejected row"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def default_output_path(input_path: Path) -> Path:
    """``data/customers.csv`` -> ``output/customers_cleaned.xlsx``."""
    return DEFAULT_OUTPUT_DIR / f"{input_path.stem}_cleaned.xlsx"


def parse_column_list(text: str) -> tuple[str, ...]:
    """Split ``"email, phone"`` into ``("email", "phone")``."""
    return tuple(part.strip() for part in text.split(",") if part.strip())


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool and return a process exit code."""
    args = build_parser().parse_args(argv)
    configure_logging(verbose=args.verbose, log_file=None if args.no_log_file else args.log_file)

    output_path = args.output or default_output_path(args.input)
    delimiter = "\t" if args.delimiter == r"\t" else args.delimiter

    try:
        config = load_config(args.config)
        if args.dedupe_on is not None:
            config = config.with_duplicate_subset(parse_column_list(args.dedupe_on))
        result = run_pipeline(
            args.input, output_path, config, sheet=args.sheet, delimiter=delimiter
        )
    except DataCleanerError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR
    except Exception:  # noqa: BLE001 - last-resort handler so users never see a raw crash
        logger.exception("Unexpected error. Please share the log file when reporting this issue.")
        return EXIT_UNEXPECTED

    report = result.report
    logger.info(
        "Done: %d clean rows written, %d rows need attention -> %s",
        report.rows_out,
        report.rows_rejected + report.duplicates_removed,
        output_path,
    )
    return EXIT_OK
