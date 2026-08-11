from __future__ import annotations

import contextlib

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class ScrubberError(Exception):
    """Base exception, caught at the CLI level and shown without a traceback."""

    pass


class InvalidNotebookError(ScrubberError):
    """Raised when the input is not a valid Jupyter notebook."""

    pass


class ProcessingError(ScrubberError):
    """Raised when an error occurs during notebook processing."""

    pass


class MissingNotesDestinationError(ScrubberError):
    """Raised when notes were collected but the caller named nowhere for them.

    The message states only what went wrong, since the remedy differs per front
    end (a flag versus a config key); callers append their own.
    """

    def __init__(self, note_count: int, note_tag: str) -> None:
        super().__init__(
            f'Found {note_count} cell(s) with note tag "{note_tag}", but '
            'nowhere to save the notes.',
        )
        self.note_count = note_count
        self.note_tag = note_tag


@contextlib.contextmanager
def reporting(context: str) -> Iterator[None]:
    """Report an OS-level failure as a :class:`ScrubberError`.

    ``context`` names what was being done when it failed.

    Raises:
        ScrubberError: If the block raises :class:`OSError`.
    """
    try:
        yield
    except OSError as e:
        raise ScrubberError(f'{context}: {e}') from e
