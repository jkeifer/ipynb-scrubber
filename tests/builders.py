"""Test data builders.

Plain functions, not fixtures. They have no setup or teardown, so making them
fixtures only meant every test that wanted one had to accept it as a parameter
-- which is why two test modules had reimplemented them locally. conftest.py
exposes them as fixtures too, for the tests already written that way.
"""

from typing import Any

from ipynb_scrubber.notebook import Cell, Notebook


def make_notebook(*cells: dict, metadata: dict | None = None) -> Notebook:
    """Build a notebook from cell dicts, filling in the boilerplate."""
    return {
        'cells': [{'metadata': {}, **cell} for cell in cells],
        'metadata': {} if metadata is None else metadata,
        'nbformat': 4,
        'nbformat_minor': 4,
    }


def code(source: str | list[str], **kw: Any) -> dict:
    """Build a code cell."""
    return {'cell_type': 'code', 'source': source, **kw}


def markdown(source: str | list[str], **kw: Any) -> dict:
    """Build a markdown cell."""
    return {'cell_type': 'markdown', 'source': source, **kw}


def raw(source: str | list[str], **kw: Any) -> dict:
    """Build a raw cell."""
    return {'cell_type': 'raw', 'source': source, **kw}


def schema_valid_notebook(*cells: dict, metadata: dict | None = None) -> Notebook:
    """Build a notebook that ``nbformat.validate()`` accepts.

    make_notebook builds the least this tool's own code needs, which is not
    the least the nbformat schema accepts. The differences are deliberate and
    belong to the output-format tests alone:

    - nbformat_minor is 5, the version that introduced cell ids. The two are
      not interchangeable: at 4.4 the schema rejects a cell carrying an ``id``
      outright, and at 4.5 a cell without one warns today and is a documented
      future hard error;
    - language_info names the notebook's language, as Jupyter writes it.

    Pair it with schema_valid_code, which supplies the fields the schema
    requires of a code cell.
    """
    return {
        **make_notebook(
            *cells,
            metadata={'language_info': {'name': 'python'}}
            if metadata is None
            else metadata,
        ),
        'nbformat_minor': 5,
    }


def schema_valid_code(source: str | list[str], **kw: Any) -> dict:
    """Build a code cell carrying every field the nbformat schema requires.

    ``outputs`` and ``execution_count`` are required of a code cell even when
    it has never been run, and ``id`` is required from nbformat 4.5 on.
    """
    return code(
        source,
        **{
            'id': 'c',
            'metadata': {},
            'outputs': [],
            'execution_count': None,
            **kw,
        },
    )


def cell(source: str, cell_type: str = 'code', **metadata: Any) -> Cell:
    """Build one cell, with keyword arguments going into its metadata.

    The ergonomics decide() tests want: they vary tags far more often than they
    vary anything else about the cell.
    """
    return {'cell_type': cell_type, 'source': source, 'metadata': metadata}
