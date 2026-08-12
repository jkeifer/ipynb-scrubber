"""A configured batch is all-or-nothing, and what it says when it is not.

``scrub-project`` stages every output beside its target and commits the lot at
the end, so a batch that fails anywhere writes none of its files. These tests
assert about the directory: which paths exist afterwards, which do not, and
that no staging temporary is left in between. The last section covers what a
failing entry reports, since a message no one can act on is the other half of
refusing to write.

Which config file the batch came from lives in tests/test_config_discovery.py.
"""

import argparse
import json

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from ipynb_scrubber import cli, project
from ipynb_scrubber.config import FileEntry
from ipynb_scrubber.exceptions import ScrubberError
from tests.builders import code, make_notebook


@pytest.fixture
def sample_notebook():
    """A notebook with a clear-tagged and an omit-tagged cell.

    A fixture rather than a module constant because several tests append a
    cell to it, and each of those must start from an unmodified copy.
    """
    return make_notebook(
        code('# Regular code'),
        code(
            '#| scrub-clear:\ndef solution():\n    return 42',
            outputs=[{'data': {'text/plain': ['42']}}],
            execution_count=1,
        ),
        code("print('instructor only')", tags=['scrub-omit']),
    )


@pytest.fixture
def note_cell():
    """A code cell that is captured to the notes file under ``note-1``."""
    return code('#| scrub-note: note-1\nsecret = 1', metadata={})


def write(path: Path, notebook: Mapping[str, Any]) -> None:
    """Serialize a notebook to ``path``.

    Typed as a Mapping rather than a dict because the builders return the
    ``Notebook`` TypedDict, which is a Mapping but not a ``dict[Any, Any]``.
    """
    path.write_text(json.dumps(notebook))


# A batch that succeeds writes everything it was asked for


def test_successful_batch_commits_every_file(
    tmp_path: Path,
    sample_notebook,
    note_cell,
    scrub_project,
):
    """Every configured output lands, and no temporary file is left behind."""
    out_dir = tmp_path / 'out'
    first_input = tmp_path / 'first.ipynb'
    last_input = tmp_path / 'last.ipynb'
    write(first_input, sample_notebook)
    with_note = {**sample_notebook, 'cells': [*sample_notebook['cells'], note_cell]}
    write(last_input, with_note)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{first_input}"
output = "{out_dir / 'first.ipynb'}"

[[files]]
input = "{last_input}"
output = "{out_dir / 'last.ipynb'}"
notes-file = "{out_dir / 'notes.md'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    assert result.stderr.count('✓ Processed') == 2
    assert sorted(p.name for p in out_dir.iterdir()) == [
        'first.ipynb',
        'last.ipynb',
        'notes.md',
    ]
    assert '## note-1' in (out_dir / 'notes.md').read_text()


def test_a_single_entry_writes_both_outputs(tmp_path: Path, sample_notebook, note_cell):
    """One entry is just a batch of one, and still writes notebook and notes."""
    sample_notebook['cells'].append(note_cell)
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)
    out_dir = tmp_path / 'out'

    project.scrub_files(
        [
            FileEntry(
                input=input_path,
                output=out_dir / 'out.ipynb',
                notes_file=out_dir / 'notes.md',
            ),
        ],
    )

    assert sorted(p.name for p in out_dir.iterdir()) == ['notes.md', 'out.ipynb']


def test_output_directory_creation(tmp_path: Path, sample_notebook, scrub_project):
    """Staging makes as much of the output's parent path as it needs to."""
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)
    output_path = tmp_path / 'deeply' / 'nested' / 'output' / 'file.ipynb'

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_path}"
output = "{output_path}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    assert output_path.exists()


def test_note_cells_with_notes_file(tmp_path: Path, sample_notebook, scrub_project):
    """A file-level notes-file entry is honored end to end."""
    sample_notebook['cells'].append(
        code(
            '#| scrub-note: note-1\ndef note_solution():\n    return "noted"',
            metadata={},
        ),
    )
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)
    notes_file = tmp_path / 'notes.md'

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
notes-file = "{notes_file}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    assert '## note-1' in notes_file.read_text()


# A batch that fails writes nothing at all


def test_failing_entry_cancels_the_whole_batch(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """The batch is all-or-nothing: one bad entry writes none of the outputs.

    The failing entry sits between two good ones, so this pins down both
    directions: the entry staged before it is thrown away, and the entry after
    it is never reached.
    """
    out_dir = tmp_path / 'out'
    first_input = tmp_path / 'first.ipynb'
    last_input = tmp_path / 'last.ipynb'
    write(first_input, sample_notebook)
    write(last_input, sample_notebook)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{first_input}"
output = "{out_dir / 'first.ipynb'}"

[[files]]
input = "{tmp_path / 'missing.ipynb'}"
output = "{out_dir / 'middle.ipynb'}"

[[files]]
input = "{last_input}"
output = "{out_dir / 'last.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'Input file not found' in result.stderr
    # Nothing succeeded, so nothing is reported as processed.
    assert '✓' not in result.stderr
    # The directory is made in order to stage into it, and is left empty:
    # no outputs, and no temporary files either.
    assert out_dir.is_dir()
    assert list(out_dir.iterdir()) == []


def test_existing_output_survives_a_failing_batch(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """A target that already exists keeps its contents when the batch fails."""
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    existing = out_dir / 'first.ipynb'
    existing.write_text('{"cells": []}')

    first_input = tmp_path / 'first.ipynb'
    write(first_input, sample_notebook)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{first_input}"
output = "{existing}"

[[files]]
input = "{tmp_path / 'missing.ipynb'}"
output = "{out_dir / 'second.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert existing.read_text() == '{"cells": []}'
    assert [p.name for p in out_dir.iterdir()] == ['first.ipynb']


def test_an_output_naming_a_directory_fails_before_anything_is_committed(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """A directory is the one target that stages cleanly and cannot be renamed.

    It takes a mode and a neighbouring temporary quite happily, so were it not
    refused during staging the batch would fail at the rename -- with every
    earlier entry already committed, which is the one thing a batch promises
    cannot happen. The entry naming it is deliberately second, so a commit that
    ran at all would be visible in the first entry's target.
    """
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    existing = out_dir / 'first.ipynb'
    existing.write_text('{"cells": []}')

    first_input = tmp_path / 'first.ipynb'
    write(first_input, sample_notebook)
    second_input = tmp_path / 'second.ipynb'
    write(second_input, sample_notebook)

    a_directory = tmp_path / 'somewhere'
    a_directory.mkdir()

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{first_input}"
output = "{existing}"

[[files]]
input = "{second_input}"
output = "{a_directory}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'must name a file' in result.stderr
    assert existing.read_text() == '{"cells": []}'
    assert list(a_directory.iterdir()) == []


def test_scrubbing_a_notebook_onto_itself_leaves_the_source_untouched(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """An entry whose output is its input must fail before anything is written.

    This is the one failure this tool cannot be allowed to have: it exists to
    derive an exercise copy and leave the original standing. An entry naming
    one path twice -- a copied line, an output never repointed -- would
    otherwise run to completion, report the file as processed, and leave the
    source holding its own scrubbed copy with every solution gone. Outside
    version control that is unrecoverable, so the bytes on disk are what this
    asserts; the sibling collision rules are checked in memory, in
    tests/test_config.py.
    """
    notebook = tmp_path / 'lesson.ipynb'
    write(notebook, sample_notebook)
    before = notebook.read_bytes()

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{notebook}"
output = "{notebook}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert notebook.read_bytes() == before
    assert '✓' not in result.stderr


# A target that cannot be written


def test_unwritable_output_reports_once_and_leaves_no_notes_file(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """Notes describe the exercise notebook, so they must not outlive its write.

    The failure is also reported once and only once, in the tool's own voice:
    the entry that could not be staged, the batch that was abandoned, and the
    exit are one event, not three.
    """
    sample_notebook['cells'].append(
        code('#| scrub-note: note-1\nsecret = 1', metadata={}),
    )
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)
    notes_file = tmp_path / 'notes.md'

    locked = tmp_path / 'locked'
    locked.mkdir()
    locked.chmod(0o500)

    config = tmp_path / '.ipynb-scrubber.toml'
    config.write_text(f'''
[[files]]
input = "{input_path}"
output = "{locked / 'sub' / 'out.ipynb'}"
notes-file = "{notes_file}"
''')

    result = scrub_project('--config-file', str(config))

    assert result.returncode == 1
    assert 'Traceback' not in result.stderr
    assert result.stderr.count('Permission denied') == 1
    assert not notes_file.exists()


def test_unwritable_notes_file_leaves_the_notebook_uncommitted(
    tmp_path: Path,
    sample_notebook,
    note_cell,
    scrub_project,
):
    """A notebook and its notes are committed together or not at all."""
    sample_notebook['cells'].append(note_cell)
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)

    # A regular file where the notes file's parent directory should be, so
    # the notes cannot be staged even though the notebook already is.
    blocker = tmp_path / 'blocker'
    blocker.write_text('not a directory')

    out_dir = tmp_path / 'out'
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_path}"
output = "{out_dir / 'out.ipynb'}"
notes-file = "{blocker / 'notes.md'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'Traceback' not in result.stderr
    assert out_dir.is_dir()
    assert list(out_dir.iterdir()) == []


def test_commit_failure_removes_staged_files(
    tmp_path: Path,
    sample_notebook,
    failing_commit,
):
    """A rename that fails is reported, and the staged files are cleaned up."""
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)
    out_dir = tmp_path / 'out'

    with pytest.raises(ScrubberError, match='Error writing output'):
        project.scrub_files(
            [FileEntry(input=input_path, output=out_dir / 'out.ipynb')],
        )

    assert list(out_dir.iterdir()) == []


# What a failing entry reports


def test_input_file_not_found(tmp_path: Path, scrub_project):
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{tmp_path / 'nonexistent.ipynb'}"
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'Input file not found' in result.stderr
    assert 'Error: ' in result.stderr


def test_invalid_json_in_notebook(tmp_path: Path, scrub_project):
    input_path = tmp_path / 'input.ipynb'
    input_path.write_text('{ invalid json')

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    # The path is named once, by the batch wrapper; the parse failure itself
    # does not know where the bytes came from.
    assert f'Error processing {input_path}: Invalid notebook JSON' in result.stderr


def test_input_that_is_a_directory_reports_os_error(tmp_path: Path, scrub_project):
    """The input path exists but can't be opened as a file (IsADirectoryError)."""
    input_dir = tmp_path / 'in.ipynb'
    input_dir.mkdir()
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_dir}"
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert f'Error reading {input_dir}' in result.stderr


def test_note_cells_without_notes_file_fails(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """A config-driven run with note cells but no notes-file is a hard error."""
    sample_notebook['cells'].append(
        code(
            '#| scrub-note: error-test\ndef note_solution():\n    return 1',
            metadata={},
        ),
    )
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'note tag' in result.stderr
    assert 'Set notes-file for this entry in the config.' in result.stderr


def test_unexpected_error_is_not_swallowed(
    tmp_path: Path,
    sample_notebook,
    monkeypatch,
):
    """A non-OSError is an internal bug and must surface, not become exit 1."""
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)

    config = tmp_path / '.ipynb-scrubber.toml'
    config.write_text(f'''
[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    def boom(*args, **kwargs):
        raise MemoryError('out of memory')

    monkeypatch.setattr(project, 'scrub', boom)

    with pytest.raises(MemoryError):
        cli.scrub_project(argparse.Namespace(config_file=config))
