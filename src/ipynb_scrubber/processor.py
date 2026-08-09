from typing import Any

from .actions import Note, Omit, apply, decide
from .config import ScrubbingOptions
from .exceptions import ProcessingError, ScrubberError
from .notebook import Cell, Notebook, get_cell_source, validate_notebook


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
                notes[action.note_id] = (index, get_cell_source(cell))

            processed.append(apply(cell, action))
        except ScrubberError as e:
            raise ProcessingError(f'Cell {index}: {e}') from e

    result: Notebook = {
        **validated,
        'cells': processed,
        'metadata': {**validated.get('metadata', {}), 'exercise_version': True},
    }
    return result, {note_id: source for note_id, (_, source) in notes.items()}
