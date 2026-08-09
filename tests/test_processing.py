import pytest

from ipynb_scrubber.config import ScrubbingOptions
from ipynb_scrubber.exceptions import ProcessingError
from ipynb_scrubber.processor import process_notebook

OPTS = ScrubbingOptions()


def notebook(*sources: tuple[str, str]):
    return {
        'cells': [
            {'cell_type': ct, 'source': src, 'metadata': {}} for ct, src in sources
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }


def test_duplicate_note_ids_error():
    nb = notebook(
        ('code', '#| scrub-note: ex-1\nSOLUTION_A = 1'),
        ('code', '#| scrub-note: ex-1\nSOLUTION_B = 2'),
    )
    with pytest.raises(ProcessingError, match=r"Cell 1.*[Dd]uplicate note id 'ex-1'"):
        process_notebook(nb, OPTS)


def test_error_is_prefixed_with_the_offending_cell_index():
    nb = notebook(
        ('code', 'a = 1'),
        ('code', 'b = 2'),
        ('code', 'c = 3'),
        ('markdown', '<!-- scrub-note: x -->'),
    )
    with pytest.raises(ProcessingError, match=r'^Cell 3: '):
        process_notebook(nb, OPTS)


def test_notes_capture_original_source_before_clearing():
    nb = notebook(('code', '#| scrub-note: ex-1\nSOLUTION = 1'))
    result, notes = process_notebook(nb, OPTS)
    assert notes == {'ex-1': ('code', '#| scrub-note: ex-1\nSOLUTION = 1')}
    assert result['cells'][0]['source'] == f'# (See notes: ex-1)\n{OPTS.clear_text}'


def test_omitted_cells_are_removed():
    nb = notebook(('code', 'keep = 1'), ('code', '#| scrub-omit\ndrop = 2'))
    result, _ = process_notebook(nb, OPTS)
    assert [c['source'] for c in result['cells']] == ['keep = 1']


def test_exercise_version_metadata_is_set():
    result, _ = process_notebook(notebook(('code', 'x = 1')), OPTS)
    assert result['metadata']['exercise_version'] is True
