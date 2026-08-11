"""Test data builders.

Plain functions, not fixtures. They have no setup or teardown, so making them
fixtures would only mean every test that wanted one had to accept it as a
parameter. Import them instead.

They build *well-formed* notebooks. A test that needs a malformed one -- no
cell_type, a non-list 'cells', tags that are not an array of strings -- should
write the literal it means, because filling in boilerplate is exactly what
those tests are checking does not happen. ``metadata=`` is the way to write
one of those: ``tags=`` below says "tags", and a test handing it a string is
saying something else.

Every cell builder reads its keyword arguments the same way: ``tags=`` goes
into the cell's metadata, where decide() reads it, and everything else is a
field of the cell itself. There is no builder that spells a keyword argument
differently, because a cell whose tags sat one level too high would look
tagged, be untagged, and say nothing about it.
"""

from typing import Any, cast

from ipynb_scrubber.notebook import Cell, Notebook


def make_notebook(*cells: Cell, metadata: dict | None = None) -> Notebook:
    """Build a notebook from cell dicts, filling in the boilerplate."""
    return {
        'cells': [{'metadata': {}, **cell} for cell in cells],
        'metadata': {} if metadata is None else metadata,
        'nbformat': 4,
        'nbformat_minor': 4,
    }


def _cell(
    cell_type: str,
    source: str | list[str],
    tags: list[str] | None,
    kw: dict[str, Any],
) -> Cell:
    """Build a cell of ``cell_type``, with ``tags`` written into its metadata.

    ``kw`` becomes fields of the cell. ``tags`` is the one keyword argument
    that does not, because decide() reads tags from ``metadata.tags`` and a
    list left at the cell's top level is a tag nothing acts on.

    Metadata composes: ``tags`` is added to whatever ``metadata=`` supplied
    rather than replacing it. The single case where the two could disagree --
    a ``metadata=`` that already carries tags -- is refused instead of being
    settled silently in either direction.

    A cell given no tags carries no metadata key at all. Cells arrive that way
    from the wild, and make_notebook fills the key in for the tests that want
    it filled, so the builders leave it to the tests that do not.

    Raises:
        TypeError: If tags are given both ways.
    """
    cell = {'cell_type': cell_type, 'source': source, **kw}

    if tags is not None:
        metadata = cell.get('metadata', {})
        if 'tags' in metadata:
            raise TypeError(
                "tags given twice: pass either tags= or a metadata= carrying 'tags'",
            )
        cell['metadata'] = {**metadata, 'tags': tags}

    return cast(Cell, cell)


def code(
    source: str | list[str],
    *,
    tags: list[str] | None = None,
    **kw: Any,
) -> Cell:
    """Build a code cell."""
    return _cell('code', source, tags, kw)


def markdown(
    source: str | list[str],
    *,
    tags: list[str] | None = None,
    **kw: Any,
) -> Cell:
    """Build a markdown cell."""
    return _cell('markdown', source, tags, kw)


def raw(
    source: str | list[str],
    *,
    tags: list[str] | None = None,
    **kw: Any,
) -> Cell:
    """Build a raw cell."""
    return _cell('raw', source, tags, kw)


def schema_valid_notebook(*cells: Cell, metadata: dict | None = None) -> Notebook:
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


def schema_valid_code(
    source: str | list[str],
    *,
    tags: list[str] | None = None,
    **kw: Any,
) -> Cell:
    """Build a code cell carrying every field the nbformat schema requires.

    ``outputs`` and ``execution_count`` are required of a code cell even when
    it has never been run, and ``id`` is required from nbformat 4.5 on. The
    ``metadata`` supplied here is the empty one the schema wants; ``tags=``
    composes with it as it does everywhere else.
    """
    return code(
        source,
        tags=tags,
        **{
            'id': 'c',
            'metadata': {},
            'outputs': [],
            'execution_count': None,
            **kw,
        },
    )
