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


class MissingNotesDestinationError(ScrubberError):
    """Raised when notes were collected but the caller named nowhere for them.

    What went wrong -- this many cells, under this tag -- is the same wherever
    the run was started from, so it is said once, here. What to do about it is
    not: one front end wants a flag and the other a config key. A front end
    catching this appends its own remedy to the message.
    """

    def __init__(self, note_count: int, note_tag: str) -> None:
        super().__init__(
            f'Found {note_count} cell(s) with note tag "{note_tag}", but '
            'nowhere to save the notes.',
        )
        self.note_count = note_count
        self.note_tag = note_tag
