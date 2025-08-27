from typing import Any, TypedDict

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


def process_cell(cell: Cell, clear_tag: str, clear_text: str) -> Cell:
    """Process a single cell.

    Args:
        cell: The cell to process
        clear_tag: Tag marking cells to clear
        clear_text: Replacement text for cleared cells

    Returns:
        Processed cell
    """
    # Clear outputs and execution count
    cell.pop('outputs', None)
    cell.pop('execution_count', None)

    # Clear content if needed
    should_clear, custom_text = should_clear_cell(cell, clear_tag)
    if should_clear:
        text_to_use = custom_text if custom_text is not None else clear_text
        cell['source'] = text_to_use + '\n'

    return cell


def process_notebook(
    notebook: Notebook,
    clear_tag: str,
    clear_text: str,
    omit_tag: str,
) -> Notebook:
    """Process a notebook to create an exercise version.

    Args:
        notebook: The input notebook to process
        clear_tag: Tag marking cells to clear
        clear_text: Replacement text for cleared cells
        omit_tag: Tag marking cells to omit entirely

    Returns:
        Processed notebook with cleared/omitted cells and exercise metadata

    Raises:
        InvalidNotebookError: If the notebook structure is invalid
        ProcessingError: If an error occurs during processing
    """
    validate_notebook(notebook)

    try:
        processed_cells = [
            process_cell(cell, clear_tag, clear_text)
            for cell in notebook.get('cells', [])
            if not should_omit_cell(cell, omit_tag)
        ]
        notebook['cells'] = processed_cells
        notebook['metadata']['exercise_version'] = True
    except Exception as e:
        raise ProcessingError(f'Error processing notebook: {e}') from e

    return notebook
