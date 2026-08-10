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


def cell(source: str, cell_type: str = 'code', **metadata: Any) -> Cell:
    """Build one cell, with keyword arguments going into its metadata.

    The ergonomics decide() tests want: they vary tags far more often than they
    vary anything else about the cell.
    """
    return {'cell_type': cell_type, 'source': source, 'metadata': metadata}
