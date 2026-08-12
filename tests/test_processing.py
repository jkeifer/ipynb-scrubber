"""What the notebook loop adds over deciding and applying one cell.

Five things, and only these belong here: notebook-level validation, the omit
skip, duplicate note ids, the ``Cell {index}: `` error prefix, and the notebook
it rebuilds -- top-level metadata merge included -- alongside the notes it
returns. What a given option on a given cell *means* is test_actions.py's, and
what a header *reads as* is test_options.py's; asserting either through this
wrapper would pin one behaviour in two places.
"""

import copy

import pytest

from ipynb_scrubber.exceptions import InvalidNotebookError, ProcessingError
from ipynb_scrubber.notebook import get_notebook_language
from ipynb_scrubber.notes import render_notes
from ipynb_scrubber.options import ScrubbingOptions
from ipynb_scrubber.processor import process_notebook
from tests.builders import code, make_notebook, markdown

OPTS = ScrubbingOptions()


def test_duplicate_note_ids_error():
    nb = make_notebook(
        code('#| scrub-note: ex-1\nSOLUTION_A = 1'),
        code('#| scrub-note: ex-1\nSOLUTION_B = 2'),
    )
    with pytest.raises(
        ProcessingError,
        match=r"Cell 1.*[Dd]uplicate note id 'ex-1'",
    ) as exc_info:
        process_notebook(nb, OPTS)
    message = str(exc_info.value)
    assert 'cell 0' in message
    assert 'Cell 1' in message


def test_error_is_prefixed_with_the_offending_cell_index():
    """One ``except`` clause prefixes every refusal, so one test covers them all.

    Which options refuse, and what each refusal says, is test_actions.py's; all
    the loop adds is the index of the cell that raised.
    """
    nb = make_notebook(
        code('a = 1'),
        code('b = 2'),
        code('c = 3'),
        markdown('<!-- scrub-note: x -->'),
    )
    with pytest.raises(ProcessingError, match=r'^Cell 3: '):
        process_notebook(nb, OPTS)


def test_internal_bug_surfaces_as_a_bug_not_a_processing_error(monkeypatch):
    """Only ScrubberError carries the friendly, traceback-free contract.

    Anything else escaping cell processing is a defect in this tool, and
    wrapping it in ProcessingError would present it to the user as though
    their notebook were at fault.
    """

    def boom(*_args, **_kwargs):
        raise RuntimeError('internal invariant violated')

    monkeypatch.setattr('ipynb_scrubber.scrubber.Scrubber.decide', boom)

    nb = make_notebook(code('x = 1'))
    with pytest.raises(RuntimeError, match='internal invariant violated'):
        process_notebook(nb, OPTS)


def test_input_notebook_is_untouched_on_success():
    """process_notebook is a function, not an in-place rewrite.

    The caller keeps their notebook; the exercise version is a separate
    object, all the way down to the cells.
    """
    nb = make_notebook(
        code(
            '#| scrub-clear:\nsecret = 1',
            outputs=[{'output_type': 'stream', 'text': ['1\n']}],
            execution_count=3,
        ),
        code('#| scrub-note: ex-1\nsolution = 2'),
    )
    before = copy.deepcopy(nb)

    result, _ = process_notebook(nb, OPTS)

    assert nb == before
    assert result is not nb
    assert result['cells'][0] is not nb['cells'][0]
    assert result['metadata'] is not nb['metadata']
    # ...and the copy really was scrubbed, so the comparison above means something
    assert result['cells'][0]['source'] == OPTS.clear_text


def test_input_notebook_is_untouched_after_a_mid_notebook_error():
    """Cell 0 is rewritable and cell 1 is fatal: an all-or-nothing check.

    Processing is atomic, so a failure part way through leaves the caller's
    notebook exactly as they handed it over, rather than half-scrubbed.
    """
    nb = make_notebook(
        code(
            '#| scrub-note: dupe\nx = 1',
            outputs=[{'output_type': 'stream', 'text': ['1\n']}],
            execution_count=3,
        ),
        code(
            '#| scrub-note: dupe\ny = 2',
            outputs=[{'output_type': 'stream', 'text': ['2\n']}],
            execution_count=4,
        ),
    )
    before = copy.deepcopy(nb)

    with pytest.raises(ProcessingError, match='Duplicate note id'):
        process_notebook(nb, OPTS)

    assert nb == before


def test_notes_capture_original_source_before_clearing():
    """The notes mapping the loop returns, and its end-to-end sanity check.

    This is the one test here that reads an option out of a cell's source and
    follows it all the way into the output: a header written by an author does
    reach the cell it marks. Every other option, spelling and message is
    exercised a layer down.
    """
    nb = make_notebook(code('#| scrub-note: ex-1\nSOLUTION = 1'))
    result, notes = process_notebook(nb, OPTS)
    assert notes == {'ex-1': 'SOLUTION = 1'}
    assert result['cells'][0]['source'] == f'# (See notes: ex-1)\n{OPTS.clear_text}'


def test_omitted_cells_are_removed():
    """The one thing an Omit means that ``apply`` cannot say: no output cell."""
    nb = make_notebook(code('keep = 1'), code('#| scrub-omit:\ndrop = 2'))
    result, _ = process_notebook(nb, OPTS)
    assert [c['source'] for c in result['cells']] == ['keep = 1']


def test_exercise_version_metadata_is_set():
    result, _ = process_notebook(make_notebook(code('x = 1')), OPTS)
    assert result['metadata']['exercise_version'] is True


def test_missing_metadata_field_is_created():
    """A notebook with no top-level metadata key still gets exercise_version."""
    nb = {'cells': [], 'nbformat': 4, 'nbformat_minor': 4}
    result, _ = process_notebook(nb, OPTS)
    assert result['metadata'] == {'exercise_version': True}


def test_unknown_top_level_fields_are_carried_through():
    """Rebuilding the notebook must not drop keys this tool does not model."""
    nb = make_notebook(code('x = 1'))
    nb['metadata']['kernelspec'] = {'name': 'python3'}
    nb['someday_field'] = 'keep me'

    result, _ = process_notebook(nb, OPTS)

    assert result['nbformat'] == 4
    assert result['nbformat_minor'] == 4
    assert result['someday_field'] == 'keep me'
    assert result['metadata']['kernelspec'] == {'name': 'python3'}


def test_empty_notebook_is_processed():
    nb = make_notebook()
    result, _ = process_notebook(nb, OPTS)
    assert result['cells'] == []
    assert result['metadata']['exercise_version'] is True


def test_notes_fence_follows_the_notebook_language():
    """A non-Python notebook gets its notes fenced in its own language."""
    nb = make_notebook(
        code('#| scrub-note: ex-1\nx <- 1'),
        metadata={'language_info': {'name': 'r'}},
    )
    _, notes = process_notebook(nb, OPTS)
    rendered = render_notes(notes, get_notebook_language(nb))
    assert '```r\nx <- 1\n```' in rendered


# --- notebook-level validation -------------------------------------------


def test_non_dict_input_errors():
    with pytest.raises(InvalidNotebookError, match='not a valid JSON object'):
        process_notebook([], OPTS)


def test_missing_cells_field_errors():
    nb = {'metadata': {}, 'nbformat': 4, 'nbformat_minor': 4}
    with pytest.raises(InvalidNotebookError, match="missing required 'cells' field"):
        process_notebook(nb, OPTS)


def test_non_list_cells_field_errors():
    nb = {'cells': 'not a list', 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 4}
    with pytest.raises(InvalidNotebookError, match="'cells' field must be a list"):
        process_notebook(nb, OPTS)


def test_non_object_notebook_metadata_is_rejected():
    """Malformed top-level metadata is bad input, not an internal bug.

    The processor merges ``exercise_version`` into this mapping, so a
    non-object here would otherwise surface as a TypeError traceback.
    """
    for bad in (None, 'oops', 42, []):
        with pytest.raises(
            InvalidNotebookError,
            match="Notebook has invalid 'metadata' field",
        ):
            process_notebook({'cells': [], 'metadata': bad}, OPTS)


def test_non_dict_cell_errors():
    nb = {'cells': ['not a dict'], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 4}
    with pytest.raises(InvalidNotebookError, match='Cell 0 is not a valid object'):
        process_notebook(nb, OPTS)


def test_cell_missing_cell_type_errors():
    nb = {
        'cells': [{'source': 'content', 'metadata': {}}],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }
    with pytest.raises(
        InvalidNotebookError,
        match="Cell 0 is missing required 'cell_type' field",
    ):
        process_notebook(nb, OPTS)


def test_cell_invalid_cell_type_errors():
    nb = {
        'cells': [{'cell_type': 'invalid_type', 'source': 'content', 'metadata': {}}],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }
    with pytest.raises(InvalidNotebookError, match='invalid cell_type'):
        process_notebook(nb, OPTS)


def test_cell_non_dict_metadata_errors():
    nb = make_notebook({'cell_type': 'code', 'source': 'x = 1', 'metadata': 'oops'})
    with pytest.raises(
        InvalidNotebookError,
        match=r"Cell 0 has invalid 'metadata' field: must be an object",
    ):
        process_notebook(nb, OPTS)


def test_cell_non_array_tags_errors():
    """tags as a bare string would make `in` do substring matching, silently

    dropping cells whose tag name happens to contain the omit tag as a
    substring; rejecting a non-array shape up front prevents that.
    """
    nb = make_notebook(
        code('x = 1', metadata={'tags': 'scrub-omit-extra'}),
    )
    with pytest.raises(
        InvalidNotebookError,
        match=r"Cell 0 has invalid 'metadata\.tags' field: "
        'must be an array of strings',
    ):
        process_notebook(nb, OPTS)


def test_cell_tags_with_non_string_items_errors():
    nb = make_notebook(code('x = 1', metadata={'tags': ['ok', 5]}))
    with pytest.raises(
        InvalidNotebookError,
        match=r"Cell 0 has invalid 'metadata\.tags' field",
    ):
        process_notebook(nb, OPTS)


def test_cell_non_string_non_list_source_errors():
    nb = make_notebook({'cell_type': 'code', 'source': 5, 'metadata': {}})
    with pytest.raises(
        InvalidNotebookError,
        match=r"Cell 0 has invalid 'source' field: "
        'must be a string or a list of strings',
    ):
        process_notebook(nb, OPTS)


def test_cell_source_list_with_non_string_items_errors():
    nb = make_notebook({'cell_type': 'code', 'source': ['ok', 5], 'metadata': {}})
    with pytest.raises(
        InvalidNotebookError,
        match=r"Cell 0 has invalid 'source' field",
    ):
        process_notebook(nb, OPTS)
