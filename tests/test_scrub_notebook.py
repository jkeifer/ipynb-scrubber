import json


def test_invalid_json_input_exits_nonzero(scrub_notebook):
    result = scrub_notebook(input_data='not json')
    assert result.returncode == 1
    assert 'Invalid JSON input' in result.stderr
    assert 'Traceback' not in result.stderr


def test_output_is_valid_json_indented_by_one(scrub_notebook, make_notebook, code):
    nb = make_notebook(code('x = 1'))
    result = scrub_notebook(input_data=json.dumps(nb))
    assert result.returncode == 0
    assert json.loads(result.stdout)
    assert '\n "cells"' in result.stdout


def test_flags_reach_the_options(scrub_notebook, make_notebook, code):
    nb = make_notebook(code('#| my-clear:\nsecret = 1'))
    result = scrub_notebook(
        '--clear-tag',
        'my-clear',
        '--clear-text',
        'REPLACED',
        input_data=json.dumps(nb),
    )
    assert json.loads(result.stdout)['cells'][0]['source'] == 'REPLACED'


def test_multiline_clear_text_flag_survives_argv(scrub_notebook, make_notebook, code):
    """A multi-line --clear-text value is passed through argv intact."""
    nb = make_notebook(code('secret', metadata={'tags': ['scrub-clear']}))
    result = scrub_notebook(
        '--clear-text',
        'def add(a, b):\n    # TODO\n    pass',
        input_data=json.dumps(nb),
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == 'def add(a, b):\n    # TODO\n    pass'


def test_note_tag_flag_reaches_the_options(scrub_notebook, make_notebook, code):
    """A custom --note-tag is used both to detect and to name the tag error."""
    nb = make_notebook(code('x = 1', metadata={'tags': ['keepme']}))
    result = scrub_notebook('--note-tag', 'keepme', input_data=json.dumps(nb))
    assert result.returncode == 1
    assert "Option 'keepme' is not supported as a cell tag" in result.stderr


def test_notes_without_notes_file_is_an_error(scrub_notebook, make_notebook, code):
    """Notes with nowhere to go is fatal, and the error names the remedy.

    The exercise notebook would reference notes by id, so emitting it without
    the notes file leaves the reader chasing a file that does not exist.
    """
    nb = make_notebook(code('#| scrub-note: ex-1\nsecret = 1'))
    result = scrub_notebook(input_data=json.dumps(nb))
    assert result.returncode == 1
    assert result.stdout == ''
    assert '--notes-file' in result.stderr
    assert 'Traceback' not in result.stderr


def test_notes_file_is_written(tmp_path, scrub_notebook, make_notebook, code):
    nb = make_notebook(code('#| scrub-note: ex-1\nsecret = 1'))
    notes = tmp_path / 'notes.md'
    result = scrub_notebook('--notes-file', str(notes), input_data=json.dumps(nb))
    assert result.returncode == 0
    assert '## ex-1' in notes.read_text()


def test_notes_file_is_not_written_when_processing_fails(
    tmp_path,
    scrub_notebook,
    make_notebook,
    code,
):
    """A validation failure leaves no partial or stale notes file on disk."""
    nb = make_notebook(code('#| scrub-note:\nsecret = 1'))  # missing id: error
    notes = tmp_path / 'notes.md'
    result = scrub_notebook('--notes-file', str(notes), input_data=json.dumps(nb))
    assert result.returncode == 1
    assert not notes.exists()


def test_no_command_exits_two(scrubber):
    result = scrubber()
    assert result.returncode == 2
    assert 'command required' in result.stderr


def test_processing_error_exits_one_without_traceback(
    scrub_notebook,
    make_notebook,
    markdown,
):
    nb = make_notebook(markdown('<!-- scrub-note: ex-1 -->'))
    result = scrub_notebook(input_data=json.dumps(nb))
    assert result.returncode == 1
    assert result.stdout == ''
    assert 'Traceback' not in result.stderr
    assert result.stderr.strip() == (
        "Error: Cell 0: Option 'scrub-note' is only supported on code cells"
    )
