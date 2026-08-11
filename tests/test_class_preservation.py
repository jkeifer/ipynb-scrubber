"""The class a mapping arrives as is the class it leaves as.

One file rather than a case each in test_actions.py and test_processing.py:
this is one promise kept by three call sites -- the cell copy, the tag rewrite
and the notebook rebuild -- and a case per site would pin one promise in three
places while still passing if a fourth site were added without it.

A local dict subclass rather than nbformat's NotebookNode, because the promise
is about any dict subclass. NotebookNode is one caller of it, and the round
trip that motivates the promise belongs to test_jupytext.py. The one exception
is test_nbformat_converts_on_assignment_but_not_construction below: it pins an
upstream fact about NotebookNode itself -- not this package's promise -- that
the per-node rebuild depends on, so nbformat is the only mapping that will do.
"""

from typing import Any

import nbformat
import pytest

from ipynb_scrubber.actions import ScrubbingOptions
from ipynb_scrubber.notebook import evolve
from ipynb_scrubber.processor import process_notebook
from tests.builders import code, make_notebook, markdown, raw

OPTS = ScrubbingOptions()


class Node(dict):
    """A dict subclass, standing in for nbformat's NotebookNode."""


def as_nodes(value: Any) -> Any:
    """``value`` with every mapping inside it rebuilt as a Node."""
    if isinstance(value, dict):
        return Node({key: as_nodes(item) for key, item in value.items()})
    if isinstance(value, list):
        return [as_nodes(item) for item in value]
    return value


def test_the_notebook_its_cells_and_their_metadata_keep_their_class():
    nb = as_nodes(
        make_notebook(
            code('answer = 42', tags=['scrub-clear']),
            code('untouched = 1'),
            markdown('# Secret', tags=['scrub-clear']),
            raw('secret raw', tags=['scrub-clear']),
        ),
    )

    processed, _ = process_notebook(nb, OPTS)

    assert type(processed) is Node
    assert type(processed['metadata']) is Node
    for cell in processed['cells']:
        assert type(cell) is Node
        assert type(cell['metadata']) is Node


def test_a_plain_dict_notebook_stays_plain():
    """The promise cuts both ways: type({}) is dict, so nothing is upgraded."""
    nb = make_notebook(code('answer = 42', tags=['scrub-clear']))

    processed, _ = process_notebook(nb, OPTS)

    assert type(processed) is dict
    assert type(processed['metadata']) is dict
    assert type(processed['cells'][0]) is dict


def test_a_cell_the_scrubber_leaves_alone_keeps_its_class():
    """An untagged cell takes the early return out of the tag rewrite."""
    nb = as_nodes(make_notebook(code('untouched = 1')))

    processed, _ = process_notebook(nb, OPTS)

    assert type(processed['cells'][0]) is Node


def test_evolve_applies_its_changes():
    original = Node({'a': 1, 'b': 2})

    updated = evolve(original, b=3, c=4)

    assert updated == {'a': 1, 'b': 3, 'c': 4}
    assert type(updated) is Node
    assert original == {'a': 1, 'b': 2}


def test_evolve_refuses_a_class_it_cannot_rebuild():
    """Loudly, rather than falling back to a dict.

    A silent fallback would lose the class somewhere further on, where the
    cause is much harder to find than the constructor that could not take it.

    Two required arguments rather than one: a constructor taking a single
    argument accepts the mapping positionally, whatever it annotates it as,
    because Python does not check annotations at runtime.
    """

    class Awkward(dict):
        def __init__(self, first: int, second: int) -> None:
            super().__init__()

    with pytest.raises(TypeError):
        evolve(Awkward(1, 2), a=2)


def test_nbformat_converts_on_assignment_but_not_construction():
    """Why each node is rebuilt where it is built, rather than once at the end.

    NotebookNode coerces a mapping to its own class on assignment but not
    through its constructor. Were the constructor to convert, one call on the
    finished notebook would do the job; it does not, so every node carries its
    own evolve. Should this ever fail, that reasoning -- and the three call
    sites it justifies -- is what to revisit.
    """
    constructed = nbformat.NotebookNode({'metadata': {'language_info': {}}})
    assert type(constructed['metadata']) is dict

    assigned = nbformat.NotebookNode()
    assigned['metadata'] = {'language_info': {}}
    assert type(assigned['metadata']) is nbformat.NotebookNode


def test_a_notebook_with_no_metadata_key_still_gets_metadata_in_its_class():
    """The invariant is total: an absent key is not an exception to it.

    ``validated.get('metadata', {})`` would default to a plain dict even for a
    Node notebook; the default must be built in the notebook's own class.
    """
    nb = Node({'cells': [Node(code('untouched = 1'))]})

    processed, _ = process_notebook(nb, OPTS)

    assert type(processed['metadata']) is Node
