import json

from collections.abc import Mapping
from typing import Any, Required, TypedDict, cast

from .exceptions import InvalidNotebookError

#: The indentation Jupyter itself writes. Matching it keeps a scrubbed notebook
#: diffable against one that has been opened and saved.
NOTEBOOK_INDENT = 1


class Cell(TypedDict, total=False):
    cell_type: str
    source: str | list[str]
    outputs: list[Any]
    execution_count: int | None
    metadata: dict[str, Any]


class Notebook(TypedDict, total=False):
    """A notebook, of which only ``cells`` and ``metadata`` are read.

    Keys absent from this definition ride along untouched.
    """

    cells: Required[list[Cell]]
    metadata: dict[str, Any]
    nbformat: int
    nbformat_minor: int


def evolve[M: Mapping[str, Any]](original: M, **changes: Any) -> M:
    """A copy of ``original`` with ``changes`` applied, in ``original``'s class.

    Rebuilding through ``type(original)`` rather than a dict literal is what
    lets a notebook parsed by a library that subclasses dict -- nbformat's
    ``NotebookNode``, and so jupytext -- be handed back to it to write. A plain
    dict in gives a plain dict out, ``type({})`` being ``dict``.

    Only the node being rebuilt is converted; its values ride along as they
    are. ``NotebookNode`` coerces a mapping to its own class on assignment but
    not through its constructor, so each node must be rebuilt where it is
    built, rather than the whole notebook converted once at the end.

    A class whose constructor will not take a single mapping cannot be rebuilt
    and raises ``TypeError``. Falling back to a dict would be worse: the class
    would go missing later, somewhere harder to trace back to here.
    """
    # type(original) is type[M], which the checker cannot know is constructible
    # from a mapping. Every mapping this tool rebuilds is.
    return type(original)({**original, **changes})  # type: ignore[call-arg]


def get_notebook_language(notebook: Notebook) -> str | None:
    """The notebook's language, or None if it declares none.

    ``metadata.language_info.name`` (written by the kernel that ran) is
    preferred over ``metadata.kernelspec.language``.
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


def to_cell_source(cell: Cell, text: str) -> str | list[str]:
    """``text``, in the shape ``cell``'s existing source is written in.

    nbformat allows one string or a list of lines, and Jupyter writes the list
    form. Preserving the shape keeps a rewritten cell from collapsing into one
    long line beside line-per-line neighbours: an unreadable diff, undone the
    moment anyone opened and saved the notebook.
    """
    if isinstance(cell.get('source'), list):
        return text.splitlines(keepends=True)
    return text


def loads_notebook(data: bytes) -> Any:
    """Parse notebook JSON from raw bytes.

    Bytes rather than text on purpose: encoding is a property of the notebook,
    not the locale. JSON is self-describing, so :func:`json.loads` reads it off
    the leading bytes; decoding here would fall back to the locale's, crashing
    on an accented notebook on a non-UTF-8 machine.

    Raises:
        UnicodeDecodeError: If ``data`` is not valid in the encoding it declares.
        json.JSONDecodeError: If it is not valid JSON.
    """
    return json.loads(data)


def dumps_notebook(notebook: Notebook) -> str:
    """Serialize a notebook the way Jupyter writes one.

    ``ensure_ascii`` is off because Jupyter's writer leaves it off: escaping to
    ``\\uXXXX`` round-trips fine but makes an unreadable diff against what
    Jupyter would write. The trailing newline is for the same reason.
    """
    return json.dumps(notebook, indent=NOTEBOOK_INDENT, ensure_ascii=False) + '\n'


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
    """Validate the input and return it narrowed to :class:`Notebook`.

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
