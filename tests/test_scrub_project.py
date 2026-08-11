import argparse
import json

from pathlib import Path

import pytest

from ipynb_scrubber import project, staging
from ipynb_scrubber.cli import ScrubProject
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


def write(path: Path, notebook: dict) -> None:
    path.write_text(json.dumps(notebook))


def test_basic_project(tmp_path: Path, sample_notebook, scrub_project):
    """Multiple files are each processed and written, with progress on stderr."""
    input_dir = tmp_path / 'lectures'
    input_dir.mkdir()
    nb1_path = input_dir / 'lesson1.ipynb'
    nb2_path = input_dir / 'lesson2.ipynb'
    write(nb1_path, sample_notebook)
    write(nb2_path, sample_notebook)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[options]
clear-text = "# GLOBAL DEFAULT"

[[files]]
input = "{nb1_path}"
output = "{tmp_path / 'exercises' / 'lesson1.ipynb'}"

[[files]]
input = "{nb2_path}"
output = "{tmp_path / 'exercises' / 'lesson2.ipynb'}"
clear-text = "# FILE SPECIFIC"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    assert '✓ Processed' in result.stderr

    output1 = tmp_path / 'exercises' / 'lesson1.ipynb'
    output2 = tmp_path / 'exercises' / 'lesson2.ipynb'
    assert output1.exists()
    assert output2.exists()

    nb1_out = json.loads(output1.read_text())
    nb2_out = json.loads(output2.read_text())

    # Global option reaches file 1; file-level override wins for file 2.
    assert nb1_out['cells'][1]['source'] == '# GLOBAL DEFAULT'
    assert nb2_out['cells'][1]['source'] == '# FILE SPECIFIC'


def test_custom_config_file_path(tmp_path: Path, sample_notebook, scrub_project):
    """--config-file points at a config file outside the discovery path."""
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)

    custom_config = tmp_path / 'custom-config.toml'
    custom_config.write_text(f'''
[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project('--config-file', str(custom_config), cwd=str(tmp_path))

    assert result.returncode == 0
    assert (tmp_path / 'output.ipynb').exists()


def test_invalid_toml(tmp_path: Path, scrub_project):
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text('[[files]\ninvalid toml')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'Invalid TOML' in result.stderr


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
    assert '✗' in result.stderr


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


def test_processing_stops_at_first_failing_file(tmp_path: Path, scrub_project):
    """A second, valid file entry is never reached once an earlier one fails."""
    config_path = tmp_path / '.ipynb-scrubber.toml'
    good_input = tmp_path / 'good.ipynb'
    write(good_input, make_notebook(code('x = 1')))
    config_path.write_text(f'''
[[files]]
input = "{tmp_path / 'missing.ipynb'}"
output = "{tmp_path / 'out1.ipynb'}"

[[files]]
input = "{good_input}"
output = "{tmp_path / 'out2.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert not (tmp_path / 'out2.ipynb').exists()


def test_output_directory_creation(tmp_path: Path, sample_notebook, scrub_project):
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


def test_relative_paths(tmp_path: Path, sample_notebook, scrub_project):
    """input/output paths in the config resolve relative to the process cwd."""
    input_dir = tmp_path / 'src'
    input_dir.mkdir()
    write(input_dir / 'notebook.ipynb', sample_notebook)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text("""
[[files]]
input = "src/notebook.ipynb"
output = "dist/notebook.ipynb"
""")

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    assert (tmp_path / 'dist' / 'notebook.ipynb').exists()


def test_pyproject_toml(tmp_path: Path, sample_notebook, scrub_project):
    """pyproject.toml's [tool.ipynb-scrubber] section is discovered and used."""
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)

    pyproject_path = tmp_path / 'pyproject.toml'
    pyproject_path.write_text(f'''
[tool.ipynb-scrubber.options]
clear-text = "# FROM PYPROJECT"

[[tool.ipynb-scrubber.files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    nb_out = json.loads((tmp_path / 'output.ipynb').read_text())
    assert nb_out['cells'][1]['source'] == '# FROM PYPROJECT'


def test_pyproject_without_ipynb_scrubber_section(tmp_path: Path, scrub_project):
    pyproject_path = tmp_path / 'pyproject.toml'
    pyproject_path.write_text("""
[tool.other-tool]
foo = "bar"
""")

    result = scrub_project(
        '--config-file',
        str(pyproject_path),
        cwd=str(tmp_path),
    )

    assert result.returncode == 1
    assert 'does not contain [tool.ipynb-scrubber] section' in result.stderr


@pytest.mark.parametrize('depth', [['subdir'], ['a', 'b', 'c']])
def test_discovery_searches_upward(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
    depth: list[str],
):
    """Config discovery walks upward from cwd, through multiple levels."""
    start_dir = tmp_path.joinpath(*depth)
    start_dir.mkdir(parents=True)

    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project(cwd=str(start_dir))

    assert result.returncode == 0
    assert (tmp_path / 'output.ipynb').exists()


def test_discovery_prefers_standalone_over_pyproject(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)

    standalone_config = tmp_path / '.ipynb-scrubber.toml'
    standalone_config.write_text(f'''
[options]
clear-text = "# FROM STANDALONE"

[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    pyproject = tmp_path / 'pyproject.toml'
    pyproject.write_text(f'''
[tool.ipynb-scrubber.options]
clear-text = "# FROM PYPROJECT"

[[tool.ipynb-scrubber.files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    nb_out = json.loads((tmp_path / 'output.ipynb').read_text())
    assert nb_out['cells'][1]['source'] == '# FROM STANDALONE'


def test_no_config_found(tmp_path: Path, scrub_project):
    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'No config file found' in result.stderr


def test_explicit_config_bypasses_discovery(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """--config-file is used verbatim, ignoring any discoverable config above it."""
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)

    parent_config = tmp_path / '.ipynb-scrubber.toml'
    parent_config.write_text(f'''
[options]
clear-text = "# FROM PARENT"

[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    specific_config = tmp_path / 'custom.toml'
    specific_config.write_text(f'''
[options]
clear-text = "# FROM CUSTOM"

[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project('--config-file', str(specific_config), cwd=str(tmp_path))

    assert result.returncode == 0
    nb_out = json.loads((tmp_path / 'output.ipynb').read_text())
    assert nb_out['cells'][1]['source'] == '# FROM CUSTOM'


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


def test_unwritable_output_reports_once_without_traceback(tmp_path, scrub_project):
    notebook = tmp_path / 'in.ipynb'
    write(notebook, make_notebook(code('x = 1')))
    locked = tmp_path / 'locked'
    locked.mkdir()
    locked.chmod(0o500)
    config = tmp_path / '.ipynb-scrubber.toml'
    config.write_text(
        f'[[files]]\ninput = "{notebook}"\noutput = "{locked}/sub/out.ipynb"\n',
    )

    result = scrub_project('--config-file', str(config))

    assert result.returncode == 1
    assert 'Traceback' not in result.stderr
    assert result.stderr.count('Permission denied') == 1


def test_failed_notebook_write_leaves_no_orphan_notes_file(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """Notes describe the exercise notebook, so they must not outlive its write."""
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
    assert not notes_file.exists()


@pytest.fixture
def note_cell():
    """A code cell that is captured to the notes file under ``note-1``."""
    return code('#| scrub-note: note-1\nsecret = 1', metadata={})


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


def test_scrubbing_a_notebook_onto_itself_leaves_the_source_untouched(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """An entry whose output is its input must fail before anything is written.

    This is the one failure this tool cannot be allowed to have: it exists to
    derive an exercise copy and leave the original standing. An entry naming
    one path twice — a copied line, an output never repointed — otherwise runs
    to completion, reports the file as processed, and leaves the source
    holding its own scrubbed copy with every solution gone. Outside version
    control that is unrecoverable, so the bytes on disk are what this asserts.
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


def test_two_entries_writing_one_output_fail_before_anything_is_written(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """The batch commits both, so the loser would vanish without a word."""
    first_input = tmp_path / 'first.ipynb'
    last_input = tmp_path / 'last.ipynb'
    write(first_input, sample_notebook)
    write(last_input, sample_notebook)
    out = tmp_path / 'out' / 'exercise.ipynb'

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{first_input}"
output = "{out}"

[[files]]
input = "{last_input}"
output = "{out}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert not out.exists()


def test_an_entry_writing_over_another_entrys_input_leaves_it_untouched(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """One entry's output being another's source destroys that source."""
    first_input = tmp_path / 'first.ipynb'
    last_input = tmp_path / 'last.ipynb'
    write(first_input, sample_notebook)
    write(last_input, sample_notebook)
    before = last_input.read_bytes()

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{first_input}"
output = "{last_input}"

[[files]]
input = "{last_input}"
output = "{tmp_path / 'out.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert last_input.read_bytes() == before


def test_commit_failure_removes_staged_files(
    tmp_path: Path,
    sample_notebook,
    monkeypatch,
):
    """A rename that fails is reported, and the staged files are cleaned up."""
    input_path = tmp_path / 'input.ipynb'
    write(input_path, sample_notebook)
    out_dir = tmp_path / 'out'

    def boom(staged):
        raise OSError('rename failed')

    # The rename itself, so commit_all's cleanup still runs -- that cleanup is
    # exactly what this test is checking.
    monkeypatch.setattr(staging, '_commit', boom)

    with pytest.raises(ScrubberError, match='Error writing output'):
        project.scrub_files(
            [FileEntry(input=input_path, output=out_dir / 'out.ipynb')],
        )

    assert list(out_dir.iterdir()) == []


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
        ScrubProject()(argparse.Namespace(config_file=config))
