from typing import Any, TypedDict

from .exceptions import InvalidNotebookError


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


def _validate_cell(i: int, cell: Any) -> None:
    """Validate a single cell's shape.

    Raises:
        InvalidNotebookError: If the cell is invalid.
    """
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

    metadata = cell.get('metadata', {})
    if not isinstance(metadata, dict):
        raise InvalidNotebookError(
            f"Cell {i} has invalid 'metadata' field: must be an object",
        )

    if 'tags' in metadata:
        tags = metadata['tags']
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise InvalidNotebookError(
                f"Cell {i} has invalid 'metadata.tags' field: "
                'must be an array of strings',
            )

    if 'source' in cell:
        source = cell['source']
        valid_source = isinstance(source, str) or (
            isinstance(source, list) and all(isinstance(line, str) for line in source)
        )
        if not valid_source:
            raise InvalidNotebookError(
                f"Cell {i} has invalid 'source' field: "
                'must be a string or a list of strings',
            )


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

    for i, cell in enumerate(notebook['cells']):
        _validate_cell(i, cell)
