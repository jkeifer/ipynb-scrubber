"""Turn a notebook into its exercise version: in memory, and end to end."""

import json

from dataclasses import dataclass
from typing import Any

from .actions import Note, Omit, apply, decide
from .config import ScrubbingOptions
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

    The input notebook is never touched. Cells are copied before they are
    rewritten and a fresh top-level dict is returned, so a failure part way
    through leaves the caller holding their original notebook rather than a
    half-scrubbed one.

    Args:
        notebook: The input notebook to process
        scrub_options: Scrubbing options containing tags and default text

    Returns:
        Tuple of (processed_notebook, notes_dict) where notes_dict maps
        note_id -> original_source for noted cells.

    Raises:
        InvalidNotebookError: If the notebook structure is invalid
        ProcessingError: If an error occurs during processing
    """
    validated = validate_notebook(notebook)

    # note_id -> (index of the cell that claimed it, that cell's source)
    notes: dict[str, tuple[int, str]] = {}
    processed: list[Cell] = []

    for index, cell in enumerate(validated['cells']):
        try:
            action = decide(cell, scrub_options)

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

            processed.append(apply(cell, action))
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
    """Everything scrubbing one notebook produces, as text ready to be written.

    Text rather than paths or handles: what the outputs contain is the same
    wherever they end up, while where they end up -- stdout, a file staged
    beside its target -- is the front end's business. Keeping those apart is
    what lets both commands share one pipeline.
    """

    #: The exercise notebook, serialized the way Jupyter writes one.
    notebook_text: str
    #: The rendered notes document, or None if no cell carried the note tag.
    notes_text: str | None
    #: How many cells were noted, so a caller with nowhere to put the notes can
    #: say how many of them it is refusing to throw away.
    note_count: int


def scrub(data: bytes, options: ScrubbingOptions) -> ScrubResult:
    """Scrub one notebook, from input bytes to the text of every output.

    The whole pipeline both commands run: parse, process, render. It reads and
    writes nothing and does not know where its input came from, so its errors
    describe the notebook rather than the source -- the caller knows whether
    that was stdin or a path, and is the one able to say so.

    Args:
        data: The raw bytes of the notebook, rather than text, because its
            encoding is a property of the notebook; see :func:`loads_notebook`.
        options: The scrubbing options to apply.

    Returns:
        The text of every output this notebook produces.

    Raises:
        ScrubberError: If the input is not a valid notebook, or a cell's option
            header cannot be honored.
    """
    try:
        notebook = loads_notebook(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # Bytes that are not JSON, and bytes not valid in the encoding they
        # declare, are both bad input: they earn the friendly contract rather
        # than a traceback.
        raise ScrubberError(f'Invalid notebook JSON: {e}') from e

    processed, notes = process_notebook(notebook, options)

    return ScrubResult(
        notebook_text=dumps_notebook(processed),
        notes_text=(
            render_notes(notes, get_notebook_language(processed)) if notes else None
        ),
        note_count=len(notes),
    )
