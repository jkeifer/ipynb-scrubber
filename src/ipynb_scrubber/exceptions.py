class ScrubberError(Exception):
    """Base exception for ipynb-scrubber errors.

    These exceptions are meant to be caught at the CLI level and
    displayed as user-friendly error messages without stack traces.
    """

    pass


class InvalidNotebookError(ScrubberError):
    """Raised when the input is not a valid Jupyter notebook."""

    pass


class ProcessingError(ScrubberError):
    """Raised when an error occurs during notebook processing."""

    pass
