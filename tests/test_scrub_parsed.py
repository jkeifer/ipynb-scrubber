"""What scrub_parsed adds over process_notebook: the notes, rendered.

The scrubbing itself belongs to test_processing.py and test_actions.py, and
the class promise to test_class_preservation.py. What belongs here is the
seam -- that notes come back as a document rather than a mapping, that there
is no document when nothing was noted, and that scrub() still produces what it
produced before it started delegating through here.
"""

import json

from ipynb_scrubber import NotebookScrubResult, scrub, scrub_parsed
from ipynb_scrubber.notebook import dumps_notebook
from ipynb_scrubber.options import ScrubbingOptions
from tests.builders import code, make_notebook

OPTS = ScrubbingOptions()


def test_notes_come_back_rendered():
    nb = make_notebook(code('#| scrub-note: ex-1\nSOLUTION = 1'))

    result = scrub_parsed(nb, OPTS)

    assert isinstance(result, NotebookScrubResult)
    assert result.note_count == 1
    assert result.notes_text is not None
    assert 'ex-1' in result.notes_text
    assert 'SOLUTION = 1' in result.notes_text


def test_nothing_noted_means_no_document():
    """None rather than an empty document: there is nothing to write."""
    nb = make_notebook(code('answer = 42', tags=['scrub-clear']))

    result = scrub_parsed(nb, OPTS)

    assert result.notes_text is None
    assert result.note_count == 0


def test_the_notebook_comes_back_scrubbed():
    nb = make_notebook(code('answer = 42', tags=['scrub-clear']))

    result = scrub_parsed(nb, OPTS)

    assert result.notebook['cells'][0]['source'] == '# TODO: Implement this'
    assert result.notebook['metadata']['exercise_version'] is True


def test_the_input_notebook_is_left_alone():
    nb = make_notebook(code('answer = 42', tags=['scrub-clear']))

    scrub_parsed(nb, OPTS)

    assert nb['cells'][0]['source'] == 'answer = 42'
    assert 'exercise_version' not in nb['metadata']


def test_scrub_agrees_with_scrub_parsed():
    """scrub() is this with a JSON reader and writer on either end.

    Pinning the two together is what keeps the delegation honest: were scrub()
    to grow a behaviour of its own, this is the test that would catch it.
    """
    nb = make_notebook(
        code('#| scrub-note: ex-1\nSOLUTION = 1'),
        code('answer = 42', tags=['scrub-clear']),
    )
    data = json.dumps(nb).encode()

    from_bytes = scrub(data, OPTS)
    from_object = scrub_parsed(nb, OPTS)

    assert from_bytes.notebook_text == dumps_notebook(from_object.notebook)
    assert from_bytes.notes_text == from_object.notes_text
    assert from_bytes.note_count == from_object.note_count
