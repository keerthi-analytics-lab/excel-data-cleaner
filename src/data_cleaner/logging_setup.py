"""Logging configuration: concise console output plus a detailed log file."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PACKAGE_LOGGER = "data_cleaner"
CONSOLE_FORMAT = "%(levelname)-7s %(message)s"
FILE_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def configure_logging(verbose: bool = False, log_file: Path | None = None) -> None:
    """Send package logs to the console (INFO, or DEBUG with ``verbose``) and a file.

    Safe to call more than once: existing handlers are closed and replaced, which
    matters on Windows where an open log file cannot be deleted.

    Args:
        verbose: Show DEBUG messages (e.g. every rejected row) on the console.
        log_file: Where to write the full DEBUG log; ``None`` disables file logging.
    """
    logger = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.DEBUG)

    # Data values can contain characters the Windows console cannot display;
    # replace them instead of crashing the log call.
    reconfigure = getattr(sys.stderr, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(errors="backslashreplace")
        except (ValueError, OSError):
            pass

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    logger.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
        logger.addHandler(file_handler)
