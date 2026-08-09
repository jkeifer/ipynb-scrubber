from pathlib import Path
from typing import Any, TypedDict

from .config import ScrubbingOptions
from .exceptions import InvalidNotebookError, ProcessingError, ScrubberError
from .options import Option, parse_cell_options


class Cell(TypedDict, total=False):
    cell_type: str
    source: str | list[str]
    outputs: list[Any]
    execution_count: int | None
    metadata: dict[str, Any]


class Notebook(TypedDict):
    cells: list[Cell]
    metadata: dict[str, Any]
    nbformat: int
    nbformat_minor: int


def get_cell_source(cell: Cell) -> str:
    """Return a cell's source as a single string."""
    source = cell.get('source', '')
    if isinstance(source, list):
        source = ''.join(source)
    return source


def validate_notebook(notebook: Any) -> None:
    """Validate that the input is a valid Jupyter notebook.

    Args:
        notebook: The notebook dictionary to validate

    Raises:
        InvalidNotebookError: If the notebook is invalid
    """
    if not isinstance(notebook, dict):
        raise InvalidNotebookError('Input is not a valid JSON object')

    if 'cells' not in notebook:
        raise InvalidNotebookError("Notebook is missing required 'cells' field")

    if not isinstance(notebook.get('cells'), list):
        raise InvalidNotebookError("Notebook 'cells' field must be a list")

    # Validate basic cell structure
    for i, cell in enumerate(notebook['cells']):
        if not isinstance(cell, dict):
            raise InvalidNotebookError(f'Cell {i} is not a valid object')

        if 'cell_type' not in cell:
            raise InvalidNotebookError(
                f"Cell {i} is missing required 'cell_type' field",
            )

        cell_type = cell['cell_type']
        if cell_type not in ('code', 'markdown', 'raw'):
            raise InvalidNotebookError(
                f"Cell {i} has invalid cell_type '{cell_type}'. "
                "Must be 'code', 'markdown', or 'raw'",
            )


def should_omit_cell(
    cell: Cell,
    options: dict[str, Option],
    omit_tag: str,
) -> bool:
    """Check if a cell should be omitted from the output.

    Args:
        cell: The cell to check
        options: Parsed source-based options for this cell
        omit_tag: Tag marking cells to omit

    Returns:
        True if the cell should be omitted
    """
    tags: list[str] = cell.get('metadata', {}).get('tags', [])
    return omit_tag in tags or omit_tag in options


def should_clear_cell(
    cell: Cell,
    options: dict[str, Option],
    clear_tag: str,
) -> tuple[bool, str | None]:
    """Check if a cell's content should be cleared and get custom text if any.

    Args:
        cell: The cell to check
        options: Parsed source-based options for this cell
        clear_tag: Tag marking cells to clear

    Returns:
        Tuple of (should_clear, custom_text):
        - (False, None): don't clear
        - (True, None): clear with default text
        - (True, str): clear with custom text

    Raises:
        ProcessingError: If the option combines inline text with a block
    """
    option = options.get(clear_tag)
    if option is not None:
        return (True, option.single_text())

    tags: list[str] = cell.get('metadata', {}).get('tags', [])
    if clear_tag in tags:
        return (True, None)

    return (False, None)


def should_note_cell(
    cell: Cell,
    options: dict[str, Option],
    note_tag: str,
) -> tuple[bool, tuple[str, str | None] | None]:
    """Check if a cell's content should be saved to notes.

    Note cells are only supported for code cells, and only via source-based
    options: the note tag requires an id, which a Jupyter metadata tag cannot
    carry.

    Args:
        cell: The cell to check
        options: Parsed source-based options for this cell
        note_tag: Tag marking cells to save to notes

    Returns:
        Tuple of (should_note, (note_id, replacement_text) | None):
        - (False, None): don't note
        - (True, (note_id, None)): note with id, use default replacement text
        - (True, (note_id, text)): note with id and custom replacement text

    Note tag format:
        #| scrub-note: note-id
        #| scrub-note: note-id | replacement text
        #| scrub-note: note-id |      (replacement text from the block below)

    The id is split from the replacement on the first pipe. A block, when
    present, always supplies the replacement and never the id.

    Raises:
        ProcessingError: If the note tag is present as a cell tag, on a
            non-code cell, without a usable id, or combining inline replacement
            text with a block
    """
    tags: list[str] = cell.get('metadata', {}).get('tags', [])
    if note_tag in tags:
        raise ProcessingError(
            f"Option '{note_tag}' is not supported as a cell tag; "
            f"write '#| {note_tag}: <id>' in a code cell's source",
        )

    option = options.get(note_tag)
    if option is None:
        return (False, None)

    if cell.get('cell_type', '') != 'code':
        raise ProcessingError(
            f"Option '{note_tag}' is only supported on code cells",
        )

    inline = option.inline or ''
    note_id, separator, remainder = inline.partition('|')
    note_id = note_id.strip()

    if not note_id:
        raise ProcessingError(
            f"Option '{note_tag}' requires an id, e.g. '{note_tag}: exercise-1'",
        )

    if option.block is not None:
        if separator and remainder.strip():
            raise ProcessingError(
                f"Option '{note_tag}' has both inline text and a block; "
                'use one or the other',
            )
        replacement: str | None = option.block
    elif separator:
        replacement = remainder.strip()
    else:
        replacement = None

    return (True, (note_id, replacement))


def process_cell(
    cell: Cell,
    cell_options: dict[str, Option],
    scrub_options: ScrubbingOptions,
    note_info: tuple[str, str | None] | None = None,
) -> Cell:
    """Process a single cell.

    Args:
        cell: The cell to process
        cell_options: Parsed source-based options for this cell
        scrub_options: Scrubbing options containing tags and default text
        note_info: Optional tuple of (note_id, replacement_text) if this is a
            note cell

    Returns:
        Processed cell
    """
    cell.pop('outputs', None)
    cell.pop('execution_count', None)

    if note_info is not None:
        note_id, replacement_text = note_info
        text_to_use = (
            replacement_text
            if replacement_text is not None
            else scrub_options.clear_text
        )
        text_to_use = '\n' + text_to_use if text_to_use else ''
        cell['source'] = f'# (See notes: {note_id}){text_to_use}'
        return cell

    should_clear, custom_text = should_clear_cell(
        cell,
        cell_options,
        scrub_options.clear_tag,
    )
    if should_clear:
        cell['source'] = (
            custom_text if custom_text is not None else scrub_options.clear_text
        )

    return cell


def process_notebook(
    notebook: Notebook,
    scrub_options: ScrubbingOptions,
) -> tuple[Notebook, dict[str, tuple[str, str]]]:
    """Process a notebook to create an exercise version.

    Args:
        notebook: The input notebook to process
        scrub_options: Scrubbing options containing tags and default text

    Returns:
        Tuple of (processed_notebook, notes_dict) where:
        - processed_notebook: Notebook with cleared/omitted cells and exercise metadata
        - notes_dict: Map of cell_id -> (cell_type, content) for noted cells

    Raises:
        InvalidNotebookError: If the notebook structure is invalid
        ProcessingError: If an error occurs during processing
    """
    validate_notebook(notebook)

    try:
        notes_dict: dict[str, tuple[str, str]] = {}
        processed_cells = []

        for index, cell in enumerate(notebook.get('cells', [])):
            try:
                cell_options = parse_cell_options(
                    cell.get('cell_type', ''),
                    get_cell_source(cell),
                )

                if should_omit_cell(cell, cell_options, scrub_options.omit_tag):
                    continue

                should_note, note_info = should_note_cell(
                    cell,
                    cell_options,
                    scrub_options.note_tag,
                )
                if should_note and note_info is not None:
                    note_id, _ = note_info
                    notes_dict[note_id] = (
                        cell.get('cell_type', 'code'),
                        get_cell_source(cell),
                    )
                    processed_cells.append(
                        process_cell(cell, cell_options, scrub_options, note_info),
                    )
                else:
                    processed_cells.append(
                        process_cell(cell, cell_options, scrub_options),
                    )
            except ScrubberError as e:
                raise ProcessingError(f'Cell {index}: {e}') from e

        notebook['cells'] = processed_cells
        notebook['metadata']['exercise_version'] = True
    except ScrubberError:
        raise
    except Exception as e:
        raise ProcessingError(f'Error processing notebook: {e}') from e

    return notebook, notes_dict


def write_notes_file(
    notes_dict: dict[str, tuple[str, str]],
    output_path: Path,
) -> None:
    """Write collected cell notes to a Markdown file.

    Args:
        notes_dict: Map of note_id -> (cell_type, content)
        output_path: Path where notes file will be written

    Raises:
        ProcessingError: If error occurs while writing notes
    """
    try:
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open('w') as f:
            # Write header
            f.write('# Notebook Notes\n\n')
            f.write(
                'This file contains the original content of cells marked '
                'for note-taking.\n\n',
            )

            # Write each note
            for note_id, (cell_type, content) in notes_dict.items():
                # Write note header with human-readable ID
                f.write(f'## {note_id}\n\n')

                # Determine fence based on cell type
                if cell_type == 'code':
                    fence = '```python\n'
                elif cell_type == 'markdown':
                    fence = '```markdown\n'
                elif cell_type == 'raw':
                    fence = '```\n'
                else:
                    fence = '```\n'

                # Write content in code fence
                f.write(fence)
                f.write(content)
                # Ensure content ends with newline
                if not content.endswith('\n'):
                    f.write('\n')
                f.write('```\n\n')

            # Write footer
            f.write('---\n')
            f.write('*Generated by ipynb-scrubber*\n')

    except Exception as e:
        raise ProcessingError(f'Error writing notes file: {e}') from e
