"""The round trip this API exists for: jupytext in, jupytext out.

test_class_preservation.py pins the promise that makes this work, with a local
dict subclass and no dependency at all. This file is the evidence that the
promise is the right one -- that a notebook jupytext parsed is one jupytext
will write, with no conversion in between.

The formats here are the text ones jupytext round-trips without help. qmd is
left out on purpose: it shells out to a quarto binary that is not a Python
dependency and will not be present.
"""

import jupytext
import pytest

from ipynb_scrubber import scrub_parsed
from ipynb_scrubber.options import ScrubbingOptions

OPTS = ScrubbingOptions()

SOURCE = """# %% [markdown]
# # Lesson

# %% tags=["scrub-clear"]
answer = 42

# %%
#| scrub-note: ex-1
#| echo: false
secret = "instructor only"

# %% tags=["scrub-omit"]
print("instructor only")

# %% tags=["keepme"]
untouched = 1
"""


@pytest.fixture
def scrubbed():
    return scrub_parsed(jupytext.reads(SOURCE, fmt='py:percent'), OPTS)


@pytest.mark.parametrize('fmt', ['py:percent', 'py:light', 'md', 'ipynb'])
def test_jupytext_writes_a_scrubbed_notebook(scrubbed, fmt):
    """No conversion between: the object goes straight back to jupytext.

    The assertions here are the ones every format shares. What a particular
    format does with a cell's own header is below, once.
    """
    written = jupytext.writes(scrubbed.notebook, fmt=fmt)

    assert 'answer = 42' not in written
    assert 'instructor only' not in written
    assert '# TODO: Implement this' in written


def test_the_percent_format_keeps_the_other_header_directives(scrubbed):
    """A shared header keeps the directives that are not this tool's."""
    written = jupytext.writes(scrubbed.notebook, fmt='py:percent')

    assert '#| echo: false' in written
    assert '# (See notes: ex-1)' in written
    # An untagged cell is untouched, tag and all.
    assert 'untouched = 1' in written
    assert 'keepme' in written


def test_the_notes_come_back(scrubbed):
    assert scrubbed.note_count == 1
    assert scrubbed.notes_text is not None
    assert 'instructor only' in scrubbed.notes_text


def test_the_result_still_satisfies_the_nbformat_schema(scrubbed):
    """jupytext builds on nbformat, so what comes back has to stay valid."""
    import nbformat

    nbformat.validate(scrubbed.notebook)
