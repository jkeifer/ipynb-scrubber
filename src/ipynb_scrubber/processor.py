from .actions import Note, Omit, apply, decide
from .config import ScrubbingOptions
from .exceptions import ProcessingError
from .notebook import Cell, Notebook, get_cell_source, validate_notebook

__all__ = [
    'Cell',
    'Notebook',
    'get_cell_source',
    'process_notebook',
    'validate_notebook',
]


def process_notebook(
    notebook: Notebook,
    scrub_options: ScrubbingOptions,
) -> tuple[Notebook, dict[str, tuple[str, str]]]:
    """Process a notebook to create an exercise version.

    Args:
        notebook: The input notebook to process
        scrub_options: Scrubbing options containing tags and default text

    Returns:
        Tuple of (processed_notebook, notes_dict) where notes_dict maps
        note_id -> (cell_type, original_source) for noted cells.

    Raises:
        InvalidNotebookError: If the notebook structure is invalid
        ProcessingError: If an error occurs during processing
    """
    validate_notebook(notebook)

    notes: dict[str, tuple[str, str]] = {}
    note_origin: dict[str, int] = {}
    processed: list[Cell] = []

    for index, cell in enumerate(notebook.get('cells', [])):
        try:
            action = decide(cell, scrub_options)

            if isinstance(action, Omit):
                continue

            if isinstance(action, Note):
                if action.note_id in notes:
                    raise ProcessingError(
                        f"Duplicate note id '{action.note_id}'; already used "
                        f'by cell {note_origin[action.note_id]}. Note ids '
                        'must be unique within a notebook',
                    )
                note_origin[action.note_id] = index
                notes[action.note_id] = (
                    cell.get('cell_type', 'code'),
                    get_cell_source(cell),
                )

            processed.append(apply(cell, action))
        except Exception as e:
            raise ProcessingError(f'Cell {index}: {e}') from e

    notebook['cells'] = processed
    metadata = notebook.get('metadata')
    if metadata is None:
        metadata = {}
        notebook['metadata'] = metadata
    metadata['exercise_version'] = True

    return notebook, notes
