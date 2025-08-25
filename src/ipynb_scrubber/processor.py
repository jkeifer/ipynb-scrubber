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


def has_quarto_option(cell: Cell, option: str) -> bool:
    """Check if a code cell has a specific Quarto option.

    Args:
        cell: A notebook cell dictionary containing cell_type and source
        option: The Quarto option name to check for (e.g., 'solution')

    Returns:
        True if the cell has the specified Quarto option set to true/yes or no value

    Example:
        >>> cell = {'cell_type': 'code', 'source': '#| solution: true\\nprint("hello")'}
        >>> has_quarto_option(cell, 'solution')
        True
    """
    if cell.get('cell_type') != 'code':
        return False

    source = cell.get('source', '')
    if isinstance(source, list):
        source = ''.join(source)

    lines = source.split('\n')
    for line in lines:
        trimmed = line.strip()
        if trimmed.startswith('#|'):
            option_part = trimmed[2:].strip()
            if ':' in option_part:
                key, value = option_part.split(':', 1)
                if key.strip() == option:
                    val = value.strip().lower()
                    if not val or val in ('true', 'yes'):
                        return True
        elif trimmed and not trimmed.startswith('#'):
            break

    return False


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
    return omit_tag in tags or has_quarto_option(cell, omit_tag)


def should_clear_cell(cell: Cell, clear_tag: str) -> bool:
    """Check if a cell's content should be cleared.

    Args:
        cell: The cell to check
        clear_tag: Tag marking cells to clear

    Returns:
        True if the cell content should be cleared
    """
    if cell.get('cell_type') != 'code':
        return False

    # Check Quarto option
    if has_quarto_option(cell, clear_tag):
        return True

    # Check cell tags
    tags: list[str] = cell.get('metadata', {}).get('tags', [])
    return clear_tag in tags


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
    if should_clear_cell(cell, clear_tag):
        cell['source'] = clear_text + '\n'

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
