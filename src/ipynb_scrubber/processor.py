"""Turn a notebook into its exercise version: in memory, and end to end."""

import json

from dataclasses import dataclass
from typing import Any

from .actions import Note, Omit, Scrubber, ScrubbingOptions
from .exceptions import ProcessingError, ScrubberError
from .notebook import (
    Cell,
    Notebook,
    dumps_notebook,
    get_notebook_language,
    loads_notebook,
    validate_notebook,
)
from .notes import render_notes


def process_notebook(
    notebook: Any,
    scrub_options: ScrubbingOptions,
) -> tuple[Notebook, dict[str, str]]:
    """Process a notebook to create an exercise version.

    The input is left untouched, and the result comes back with a mapping of
    note_id -> original source.

    Raises:
        InvalidNotebookError: If the notebook structure is invalid
        ProcessingError: If an error occurs during processing
    """
    validated = validate_notebook(notebook)
    scrubber = Scrubber.for_options(scrub_options)

    # note_id -> (index of the cell that claimed it, that cell's source)
    notes: dict[str, tuple[int, str]] = {}
    processed: list[Cell] = []

    for index, cell in enumerate(validated['cells']):
        try:
            action = scrubber.decide(cell)

            if isinstance(action, Omit):
                continue

            if isinstance(action, Note):
                claimed_by = notes.get(action.note_id)
                if claimed_by is not None:
                    raise ProcessingError(
                        f"Duplicate note id '{action.note_id}'; already used "
                        f'by cell {claimed_by[0]}. Note ids '
                        'must be unique within a notebook',
                    )
                notes[action.note_id] = (index, action.body)

            processed.append(scrubber.apply(cell, action))
        except ScrubberError as e:
            raise ProcessingError(f'Cell {index}: {e}') from e

    result: Notebook = {
        **validated,
        'cells': processed,
        'metadata': {**validated.get('metadata', {}), 'exercise_version': True},
    }
    return result, {note_id: source for note_id, (_, source) in notes.items()}


@dataclass(frozen=True)
class ScrubResult:
    """Everything scrubbing one notebook produces, as text ready to be written."""

    #: The exercise notebook, serialized the way Jupyter writes one.
    notebook_text: str
    #: The rendered notes document, or None if no cell carried the note tag.
    notes_text: str | None
    #: How many cells were noted, so a caller with nowhere to put the notes can
    #: say how many it is refusing to throw away.
    note_count: int


def scrub(data: bytes, options: ScrubbingOptions) -> ScrubResult:
    """Scrub one notebook, from input bytes to the text of every output.

    The whole pipeline both commands run; it touches no files, so its errors
    describe the notebook rather than the source.

    Raises:
        ScrubberError: On a bad notebook or an unhonorable option header.
    """
    try:
        notebook = loads_notebook(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # Both bad input, and so worth a friendly error rather than a traceback.
        raise ScrubberError(f'Invalid notebook JSON: {e}') from e

    processed, notes = process_notebook(notebook, options)

    return ScrubResult(
        notebook_text=dumps_notebook(processed),
        notes_text=(
            render_notes(notes, get_notebook_language(processed)) if notes else None
        ),
        note_count=len(notes),
    )
