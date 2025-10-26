from pathlib import Path
from typing import Any, TypedDict

from .config import ScrubbingOptions
from .exceptions import InvalidNotebookError, ProcessingError


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


def get_option_value(cell: Cell, option: str) -> tuple[bool, str | None]:
    """Get the value of a cell clearing option from a notebook cell.

    Uses cell-type-appropriate syntax:
    - Code cells: Quarto options (#| option: value)
    - Markdown cells: HTML comments (<!-- option: value -->)
    - Raw cells: Not supported (use metadata tags only)

    Args:
        cell: A notebook cell dictionary containing cell_type and source
        option: The option name to check for

    Returns:
        Tuple of (enabled, custom_text):
        - (False, None): option not present
        - (True, None): option present, use default text
        - (True, str): option present with custom text (including empty string)

    Example:
        >>> cell = {
        ...     'cell_type': 'code',
        ...     'source': '#| scrub-clear\\nprint("hello")',
        ... }
        >>> get_option_value(cell, 'scrub-clear')
        (True, None)
        >>> cell = {
        ...     'cell_type': 'markdown',
        ...     'source': '<!-- scrub-clear: Custom text -->\\n## Question',
        ... }
        >>> get_option_value(cell, 'scrub-clear')
        (True, 'Custom text')
    """
    cell_type = cell.get('cell_type')

    if cell_type == 'code':
        start_marker = '#|'
        end_suffix = ''
    elif cell_type == 'markdown':
        start_marker = '<!--'
        end_suffix = '-->'
    else:
        # Other cell types (raw) do not support options
        return (False, None)

    source = cell.get('source', '')
    if isinstance(source, list):
        source = ''.join(source)

    lines = source.split('\n')
    for line in lines:
        trimmed = line.strip()
        if trimmed.startswith(start_marker):
            # Extract the option part
            option_part = trimmed[len(start_marker) :].removesuffix(end_suffix).strip()
            if ':' in option_part:
                key, value = option_part.split(':', 1)
                if key.strip() == option:
                    return (True, value.lstrip())
            else:
                if option_part == option:
                    return (True, None)
        elif trimmed and not trimmed.startswith(start_marker):
            break

    return (False, None)


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


def should_omit_cell(cell: Cell, omit_tag: str) -> bool:
    """Check if a cell should be omitted from the output.

    Args:
        cell: The cell to check
        omit_tag: Tag marking cells to omit

    Returns:
        True if the cell should be omitted
    """
    tags: list[str] = cell.get('metadata', {}).get('tags', [])
    enabled, _ = get_option_value(cell, omit_tag)
    return omit_tag in tags or enabled


def should_clear_cell(cell: Cell, clear_tag: str) -> tuple[bool, str | None]:
    """Check if a cell's content should be cleared and get custom text if any.

    Args:
        cell: The cell to check
        clear_tag: Tag marking cells to clear

    Returns:
        Tuple of (should_clear, custom_text):
        - (False, None): don't clear
        - (True, None): clear with default text
        - (True, str): clear with custom text
    """
    # Check source-based options for code and markdown cells (supports custom text)
    if cell.get('cell_type') in ['code', 'markdown']:
        enabled, custom_text = get_option_value(cell, clear_tag)
        if enabled:
            return (True, custom_text)

    # Check cell tags as fallback for all cell types (no custom text support)
    tags: list[str] = cell.get('metadata', {}).get('tags', [])
    if clear_tag in tags:
        return (True, None)

    return (False, None)


def should_note_cell(
    cell: Cell,
    note_tag: str,
) -> tuple[bool, tuple[str, str | None] | None]:
    """Check if a cell's content should be saved to notes.

    Note cells are only supported for code cells. The note tag requires an ID.

    Args:
        cell: The cell to check
        note_tag: Tag marking cells to save to notes

    Returns:
        Tuple of (should_note, (note_id, replacement_text) | None):
        - (False, None): don't note
        - (True, (note_id, None)): note with ID, use default replacement text
        - (True, (note_id, text)): note with ID and custom replacement text

    Note tag format:
        #| scrub-note: note-id | replacement text
        - note-id is required
        - replacement text is optional (separated by |)
    """
    # Only support notes for code cells
    if cell.get('cell_type') != 'code':
        return (False, None)

    # Check source-based options
    enabled, custom_text = get_option_value(cell, note_tag)
    if enabled:
        if custom_text is None:
            # No ID provided, skip this cell
            return (False, None)

        # Parse the custom_text to extract note_id and optional replacement
        # Format: "note-id | replacement" or just "note-id"
        if ' | ' in custom_text:
            parts = custom_text.split(' | ', 1)
            note_id = parts[0].strip()
            replacement = parts[1].strip() if len(parts) > 1 else None
        else:
            note_id = custom_text.strip()
            replacement = None

        if not note_id:
            # Empty ID, skip
            return (False, None)

        return (True, (note_id, replacement))

    # Check cell tags (also requires ID, but tags don't support it)
    # So we skip tag-based notes
    return (False, None)


def process_cell(
    cell: Cell,
    options: ScrubbingOptions,
    note_info: tuple[str, str | None] | None = None,
) -> Cell:
    """Process a single cell.

    Args:
        cell: The cell to process
        options: Scrubbing options containing tags and default text
        note_info: Optional tuple of (note_id, replacement_text) if this is a note cell

    Returns:
        Processed cell
    """
    # Clear outputs and execution count
    cell.pop('outputs', None)
    cell.pop('execution_count', None)

    # Check if this is a note cell
    if note_info is not None:
        note_id, replacement_text = note_info
        # Use custom replacement or default
        text_to_use = (
            replacement_text if replacement_text is not None else options.clear_text
        )
        # Add reference comment
        cell['source'] = f'{text_to_use}\n# (See notes: {note_id})\n'
        return cell

    # Clear content if needed
    should_clear, custom_text = should_clear_cell(cell, options.clear_tag)
    if should_clear:
        text_to_use = custom_text if custom_text is not None else options.clear_text
        cell['source'] = text_to_use + '\n'

    return cell


def process_notebook(
    notebook: Notebook,
    options: ScrubbingOptions,
) -> tuple[Notebook, dict[str, tuple[str, str]]]:
    """Process a notebook to create an exercise version.

    Args:
        notebook: The input notebook to process
        options: Scrubbing options containing tags and default text

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

        for cell in notebook.get('cells', []):
            # Skip omitted cells
            if should_omit_cell(cell, options.omit_tag):
                continue

            # Check if cell should be noted - capture BEFORE processing
            should_note, note_info = should_note_cell(cell, options.note_tag)
            if should_note and note_info is not None:
                note_id, _ = note_info

                # Get cell type and source (original, before clearing)
                cell_type = cell.get('cell_type', 'code')
                source = cell.get('source', '')
                if isinstance(source, list):
                    source = ''.join(source)

                # Store note with note_id as key
                notes_dict[note_id] = (cell_type, source)

                # Process cell with note info to add reference comment
                processed_cells.append(process_cell(cell, options, note_info))
            else:
                # Process cell normally
                processed_cells.append(process_cell(cell, options))

        notebook['cells'] = processed_cells
        notebook['metadata']['exercise_version'] = True
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
