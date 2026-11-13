"""Custom exceptions used across the package.

Every error the tool raises on purpose inherits from :class:`DataCleanerError`,
so the command-line interface can catch them in one place and show a clear,
friendly message instead of a Python traceback.
"""


class DataCleanerError(Exception):
    """Base class for all expected (user-facing) errors."""


class ConfigError(DataCleanerError):
    """The configuration file is missing, malformed, or contains invalid rules."""


class InputFileError(DataCleanerError):
    """The input file does not exist, has an unsupported type, or cannot be read."""


class EmptyInputError(InputFileError):
    """The input file contains no columns or no data rows."""


class MissingColumnError(DataCleanerError):
    """The configuration refers to columns that are not present in the input."""


class OutputFileError(DataCleanerError):
    """The output workbook could not be written (e.g. it is open in Excel)."""
