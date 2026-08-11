import argparse
import errno
import io
import json
import subprocess
import sys

import pytest

from ipynb_scrubber import cli
from ipynb_scrubber.actions import OPTIONS, ScrubbingOptions
from ipynb_scrubber.exceptions import ScrubberError
from tests.builders import code, make_notebook, markdown, raw


def test_invalid_json_input_exits_nonzero(scrub_notebook):
    result = scrub_notebook(input_data='not json')
    assert result.returncode == 1
    assert 'Invalid notebook JSON' in result.stderr
    assert 'Traceback' not in result.stderr


def test_output_is_valid_json_indented_by_one(scrub_notebook):
    nb = make_notebook(code('x = 1'))
    result = scrub_notebook(input_data=json.dumps(nb))
    assert result.returncode == 0
    assert json.loads(result.stdout)
    assert '\n "cells"' in result.stdout


def test_flags_reach_the_options(scrub_notebook):
    nb = make_notebook(code('#| my-clear:\nsecret = 1'))
    result = scrub_notebook(
        '--clear-tag',
        'my-clear',
        '--clear-text',
        'REPLACED',
        input_data=json.dumps(nb),
    )
    assert json.loads(result.stdout)['cells'][0]['source'] == 'REPLACED'


def test_multiline_clear_text_flag_survives_argv(scrub_notebook):
    """A multi-line --clear-text value is passed through argv intact."""
    nb = make_notebook(code('secret', tags=['scrub-clear']))
    result = scrub_notebook(
        '--clear-text',
        'def add(a, b):\n    # TODO\n    pass',
        input_data=json.dumps(nb),
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == 'def add(a, b):\n    # TODO\n    pass'


def test_clear_text_markdown_flag_is_accepted(scrub_notebook):
    """Every registered option gets a flag, this one included."""
    nb = make_notebook(code('x = 1'))
    result = scrub_notebook(
        '--clear-text-markdown',
        '_TODO_',
        input_data=json.dumps(nb),
    )
    assert result.returncode == 0


def test_clear_text_raw_flag_reaches_the_options(scrub_notebook):
    nb = make_notebook(raw('secret', tags=['scrub-clear']))
    result = scrub_notebook(
        '--clear-text-raw',
        'FILL THIS IN',
        input_data=json.dumps(nb),
    )
    assert json.loads(result.stdout)['cells'][0]['source'] == 'FILL THIS IN'


def test_note_reference_flag_reaches_the_options(tmp_path, scrub_notebook):
    nb = make_notebook(code('#| scrub-note: ex-1\nsecret = 1'))
    result = scrub_notebook(
        '--note-reference',
        '// (See notes: {id})',
        '--notes-file',
        str(tmp_path / 'notes.md'),
        input_data=json.dumps(nb),
    )
    source = json.loads(result.stdout)['cells'][0]['source']
    assert source.startswith('// (See notes: ex-1)')


def test_note_tag_flag_reaches_the_options(scrub_notebook):
    """A custom --note-tag is used both to detect and to name the tag error."""
    nb = make_notebook(code('x = 1', tags=['keepme']))
    result = scrub_notebook('--note-tag', 'keepme', input_data=json.dumps(nb))
    assert result.returncode == 1
    assert "Option 'keepme' is not supported as a cell tag" in result.stderr


def test_notes_without_notes_file_is_an_error(scrub_notebook):
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


def test_notes_file_is_written(tmp_path, scrub_notebook):
    nb = make_notebook(code('#| scrub-note: ex-1\nsecret = 1'))
    notes = tmp_path / 'notes.md'
    result = scrub_notebook('--notes-file', str(notes), input_data=json.dumps(nb))
    assert result.returncode == 0
    assert '## ex-1' in notes.read_text()


def test_notes_file_is_not_written_when_processing_fails(tmp_path, scrub_notebook):
    """A validation failure leaves no partial or stale notes file on disk."""
    nb = make_notebook(code('#| scrub-note:\nsecret = 1'))  # missing id: error
    notes = tmp_path / 'notes.md'
    result = scrub_notebook('--notes-file', str(notes), input_data=json.dumps(nb))
    assert result.returncode == 1
    assert not notes.exists()


def test_failed_notebook_write_leaves_no_orphan_notes_file(tmp_path):
    """Notes describe the exercise notebook, so they must not outlive its write.

    stdout is handed a descriptor opened for reading, so every write to it
    fails the way writing into a pipe whose reader has gone away fails. This
    runs its own subprocess rather than using the fixture because the fixture
    captures stdout, and capturing it is precisely what must not happen here.
    """
    nb = make_notebook(code('#| scrub-note: ex-1\nsecret = 1'))
    notes = tmp_path / 'notes.md'
    sink = tmp_path / 'sink'
    sink.touch()

    with sink.open('rb') as read_only:
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'ipynb_scrubber.cli',
                'scrub-notebook',
                '--notes-file',
                str(notes),
            ],
            input=json.dumps(nb),
            text=True,
            stdout=read_only,
            stderr=subprocess.PIPE,
        )

    assert result.returncode == 1
    # The errno and the platform's wording for it belong to libc, so only the
    # part this tool is responsible for is asserted.
    assert 'Traceback' not in result.stderr
    assert 'Error writing output' in result.stderr
    # Neither the notes file nor the temporary it was staged as.
    assert [p.name for p in tmp_path.iterdir()] == ['sink']


def test_failed_notebook_write_survives_a_stdout_without_a_descriptor(
    tmp_path,
    monkeypatch,
):
    """Discarding stdout's buffer must not itself become the failure reported.

    A stdout that buffers in memory has no descriptor to redirect, which is how
    stdout arrives under pytest's own capture. The write failure is still the
    only thing the user should hear about.
    """

    class FailingBuffer:
        def write(self, data):
            raise OSError(errno.EPIPE, 'Broken pipe')

        def flush(self):
            pass

    class NoDescriptor:
        buffer = FailingBuffer()

        def fileno(self):
            raise io.UnsupportedOperation('fileno')

    class Stdin:
        pass

    nb = make_notebook(code('#| scrub-note: ex-1\nsecret = 1'))
    notes = tmp_path / 'notes.md'

    stdin = Stdin()
    stdin.buffer = io.BytesIO(json.dumps(nb).encode())
    monkeypatch.setattr(sys, 'stdin', stdin)
    monkeypatch.setattr(sys, 'stdout', NoDescriptor())

    args = argparse.Namespace(notes_file=notes)
    for option in OPTIONS:
        setattr(args, option.field, getattr(ScrubbingOptions(), option.field))

    with pytest.raises(ScrubberError, match='Error writing output'):
        cli.scrub_notebook(args)
    assert not notes.exists()
    assert list(tmp_path.iterdir()) == []


def test_no_command_exits_two(scrubber):
    result = scrubber()
    assert result.returncode == 2
    assert 'command required' in result.stderr


def test_processing_error_exits_one_without_traceback(scrub_notebook):
    nb = make_notebook(markdown('<!-- scrub-note: ex-1 -->'))
    result = scrub_notebook(input_data=json.dumps(nb))
    assert result.returncode == 1
    assert result.stdout == ''
    assert 'Traceback' not in result.stderr
    assert result.stderr.strip() == (
        "Error: Cell 0: Option 'scrub-note' is only supported on code cells"
    )
