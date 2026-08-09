from typing import Any, Required, TypedDict, cast

from .exceptions import InvalidNotebookError


class Cell(TypedDict, total=False):
    cell_type: str
    source: str | list[str]
    outputs: list[Any]
    execution_count: int | None
    metadata: dict[str, Any]


class Notebook(TypedDict, total=False):
    """A notebook, as far as this tool is concerned.

    ``cells`` is the only required key, and ``cells`` and ``metadata`` are the
    only two this tool reads; :func:`validate_notebook` checks the shape of
    both. ``nbformat`` and ``nbformat_minor`` are declared because notebooks
    carry them, but they are never inspected. Keys absent from this definition
    ride along untouched.
    """

    cells: Required[list[Cell]]
    metadata: dict[str, Any]
    nbformat: int
    nbformat_minor: int


def get_notebook_language(notebook: Notebook) -> str | None:
    """Return the notebook's programming language, if it declares one.

    Jupyter records this in either ``metadata.language_info.name`` or
    ``metadata.kernelspec.language``; the former is written by the kernel that
    actually ran and so is preferred. Either may be missing or malformed, in
    which case the caller supplies its own default.
    """
    metadata = notebook.get('metadata', {})
    for section, key in (('language_info', 'name'), ('kernelspec', 'language')):
        value = metadata.get(section, {})
        if isinstance(value, dict) and isinstance(value.get(key), str):
            language: str = value[key]
            return language
    return None


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


def validate_notebook(notebook: Any) -> Notebook:
    """Validate that the input is a valid Jupyter notebook.

    Args:
        notebook: The notebook dictionary to validate

    Returns:
        The same object, narrowed to :class:`Notebook`. This is the one place
        the untyped input becomes typed, so downstream code gets checked
        instead of merely asserted.

    Raises:
        InvalidNotebookError: If the notebook is invalid
    """
    if not isinstance(notebook, dict):
        raise InvalidNotebookError('Input is not a valid JSON object')

    if 'cells' not in notebook:
        raise InvalidNotebookError("Notebook is missing required 'cells' field")

    if not isinstance(notebook.get('cells'), list):
        raise InvalidNotebookError("Notebook 'cells' field must be a list")

    if 'metadata' in notebook and not isinstance(notebook['metadata'], dict):
        raise InvalidNotebookError(
            "Notebook has invalid 'metadata' field: must be an object",
        )

    for i, cell in enumerate(notebook['cells']):
        _validate_cell(i, cell)

    return cast(Notebook, notebook)
