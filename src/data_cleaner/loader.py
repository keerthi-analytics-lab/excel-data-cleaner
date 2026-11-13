"""Read CSV and Excel files into a pandas DataFrame.

Every column is read as text (``dtype=str``) and pandas' automatic "NA"
detection is switched off. This is deliberate: the cleaning steps decide what
counts as missing and how to convert numbers and dates, so nothing is silently
changed while loading (for example, ZIP codes keep their leading zeros).
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import pandas as pd

from data_cleaner.exceptions import EmptyInputError, InputFileError

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".csv", ".xlsx", ".xlsm"})

# Tried in order. "utf-8-sig" also handles the byte-order mark Excel adds to
# "CSV UTF-8" exports; cp1252 covers the default Windows Excel CSV encoding;
# latin-1 accepts any byte, so it is the final fallback.
CSV_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp1252", "latin-1")


def load_table(path: str | Path, sheet: str | None = None, delimiter: str = ",") -> pd.DataFrame:
    """Load a CSV or Excel file with every value as text.

    Args:
        path: Path to a ``.csv``, ``.xlsx`` or ``.xlsm`` file.
        sheet: Worksheet name for Excel files (defaults to the first sheet).
        delimiter: Field separator for CSV files.

    Returns:
        A DataFrame whose column names are strings and whose values are text
        or missing.

    Raises:
        InputFileError: the file is missing, unsupported, or unreadable.
        EmptyInputError: the file has no columns or no data rows.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise InputFileError(f"Input file not found: {file_path}")

    extension = file_path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise InputFileError(
            f"Unsupported file type '{extension or '(none)'}' for {file_path.name}. "
            f"Supported types: {supported}"
        )

    if file_path.stat().st_size == 0:
        raise EmptyInputError(f"Input file is empty (0 bytes): {file_path}")

    if extension == ".csv":
        frame = _read_csv(file_path, delimiter)
    else:
        frame = _read_excel(file_path, sheet)

    if len(frame.columns) == 0:
        raise EmptyInputError(f"No columns found in {file_path.name}")
    if frame.empty:
        raise EmptyInputError(f"{file_path.name} has a header row but no data rows")

    frame.columns = [str(column) for column in frame.columns]
    logger.info(
        "Loaded %d rows x %d columns from %s", len(frame), len(frame.columns), file_path.name
    )
    return frame.astype(object)


def _read_csv(file_path: Path, delimiter: str) -> pd.DataFrame:
    """Read a CSV file, trying each encoding in :data:`CSV_ENCODINGS`."""
    for encoding in CSV_ENCODINGS:
        try:
            frame = pd.read_csv(
                file_path,
                dtype=str,
                keep_default_na=False,
                encoding=encoding,
                sep=delimiter,
            )
        except UnicodeDecodeError:
            logger.debug("Could not decode %s as %s, trying next encoding", file_path, encoding)
            continue
        except pd.errors.EmptyDataError as exc:
            raise EmptyInputError(f"No columns found in {file_path.name}") from exc
        except pd.errors.ParserError as exc:
            raise InputFileError(f"Could not parse CSV file {file_path.name}: {exc}") from exc

        if encoding != CSV_ENCODINGS[0]:
            logger.warning("%s is not UTF-8; read it using %s encoding", file_path.name, encoding)
        return frame

    # latin-1 decodes any byte sequence, so this line is only a safety net.
    raise InputFileError(f"Could not decode {file_path.name} with any supported encoding")


def _read_excel(file_path: Path, sheet: str | None) -> pd.DataFrame:
    """Read one worksheet from an Excel workbook."""
    try:
        return pd.read_excel(
            file_path,
            sheet_name=sheet if sheet is not None else 0,
            dtype=str,
            keep_default_na=False,
            engine="openpyxl",
        )
    except ValueError as exc:
        # pandas raises ValueError for a missing worksheet name.
        raise InputFileError(f"Could not read {file_path.name}: {exc}") from exc
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise InputFileError(
            f"{file_path.name} is not a valid Excel workbook or is corrupted: {exc}"
        ) from exc
