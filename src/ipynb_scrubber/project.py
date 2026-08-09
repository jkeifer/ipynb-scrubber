"""Run a configured scrubbing job: read a notebook, scrub it, write results."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from .exceptions import ScrubberError
from .notes import write_notes_file
from .processor import process_notebook

if TYPE_CHECKING:
    from .config import FileEntry


def scrub_file(entry: FileEntry) -> None:
    """Scrub the notebook described by a config entry.

    Reads ``entry.input``, scrubs it with ``entry.options``, and writes the
    exercise notebook to ``entry.output`` and any notes to
    ``entry.notes_file``.

    Args:
        entry: A file entry carrying fully resolved scrubbing options.

    Raises:
        ScrubberError: If the input is missing, unreadable or not a valid
            notebook, if notes were collected but the entry names no notes
            file, or if an output cannot be written.
    """
    notes_file = entry.notes_file

    if not entry.input.exists():
        raise ScrubberError(f'Input file not found: {entry.input}')

    try:
        with entry.input.open() as f:
            notebook = json.load(f)
    except json.JSONDecodeError as e:
        raise ScrubberError(f'Invalid JSON in {entry.input}: {e}') from e
    except OSError as e:
        raise ScrubberError(f'Error reading {entry.input}: {e}') from e

    processed_notebook, notes = process_notebook(notebook, entry.options)

    if notes and notes_file is None:
        raise ScrubberError(
            f'Found {len(notes)} cell(s) with note tag '
            f'"{entry.options.note_tag}", but no notes-file specified in config',
        )

    # The notebook is written before the notes: a notes file is only
    # meaningful alongside the exercise notebook it annotates, so writing it
    # first would leave an orphan behind whenever the notebook write fails.
    try:
        entry.output.parent.mkdir(parents=True, exist_ok=True)
        with entry.output.open('w') as f:
            json.dump(processed_notebook, f, indent=1)
    except OSError as e:
        raise ScrubberError(f'Error writing {entry.output}: {e}') from e

    if notes and notes_file is not None:
        write_notes_file(notes, notes_file)
