import json

from pathlib import Path

import pytest

from ipynb_scrubber.processor import Notebook


@pytest.fixture(scope='session')
def scrub_project(scrubber):
    def inner(*args: str, input_data: str | None = None, **kwargs):
        return scrubber('scrub-project', *args, input_data=input_data, **kwargs)

    return inner


@pytest.fixture
def sample_notebook() -> Notebook:
    """Create a sample notebook with solution cells."""
    return {
        'cells': [
            {
                'cell_type': 'code',
                'source': '# Regular code',
                'metadata': {},
            },
            {
                'cell_type': 'code',
                'source': '#| scrub-clear\ndef solution():\n    return 42',
                'metadata': {},
                'outputs': [{'data': {'text/plain': ['42']}}],
                'execution_count': 1,
            },
            {
                'cell_type': 'code',
                'source': "print('instructor only')",
                'metadata': {'tags': ['scrub-omit']},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }


def test_basic_project(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test basic project scrubbing with config file."""
    # Create input notebooks
    input_dir = tmp_path / 'lectures'
    input_dir.mkdir()

    nb1_path = input_dir / 'lesson1.ipynb'
    nb2_path = input_dir / 'lesson2.ipynb'

    with nb1_path.open('w') as f:
        json.dump(sample_notebook, f)
    with nb2_path.open('w') as f:
        json.dump(sample_notebook, f)

    # Create config file
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{nb1_path}"
output = "{tmp_path / 'exercises' / 'lesson1.ipynb'}"

[[files]]
input = "{nb2_path}"
output = "{tmp_path / 'exercises' / 'lesson2.ipynb'}"
''')

    # Run scrub-project
    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    assert '✓ Processed' in result.stderr

    # Verify output files exist and are correct
    output1 = tmp_path / 'exercises' / 'lesson1.ipynb'
    output2 = tmp_path / 'exercises' / 'lesson2.ipynb'

    assert output1.exists()
    assert output2.exists()

    with output1.open() as f:
        nb1_out = json.load(f)

    # Check that cells were processed correctly
    assert len(nb1_out['cells']) == 2  # omit cell removed
    assert nb1_out['cells'][0]['source'] == '# Regular code'
    assert nb1_out['cells'][1]['source'] == '# TODO: Implement this\n'
    assert 'outputs' not in nb1_out['cells'][1]
    assert nb1_out['metadata']['exercise_version'] is True


def test_global_options(tmp_path: Path, sample_notebook: Notebook, scrub_project):
    """Test global options in config file."""
    input_path = tmp_path / 'input.ipynb'
    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[options]
clear-tag = "scrub-clear"
clear-text = "# YOUR CODE HERE"
omit-tag = "scrub-omit"

[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0

    output_path = tmp_path / 'output.ipynb'
    with output_path.open() as f:
        nb_out = json.load(f)

    # Check that custom clear text was used
    assert nb_out['cells'][1]['source'] == '# YOUR CODE HERE\n'


def test_file_specific_overrides(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test that file-specific options override global options."""
    input1_path = tmp_path / 'input1.ipynb'
    input2_path = tmp_path / 'input2.ipynb'

    with input1_path.open('w') as f:
        json.dump(sample_notebook, f)
    with input2_path.open('w') as f:
        json.dump(sample_notebook, f)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[options]
clear-text = "# GLOBAL DEFAULT"

[[files]]
input = "{input1_path}"
output = "{tmp_path / 'output1.ipynb'}"

[[files]]
input = "{input2_path}"
output = "{tmp_path / 'output2.ipynb'}"
clear-text = "# FILE SPECIFIC"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0

    # Check first file uses global default
    with (tmp_path / 'output1.ipynb').open() as f:
        nb1 = json.load(f)
    assert nb1['cells'][1]['source'] == '# GLOBAL DEFAULT\n'

    # Check second file uses file-specific override
    with (tmp_path / 'output2.ipynb').open() as f:
        nb2 = json.load(f)
    assert nb2['cells'][1]['source'] == '# FILE SPECIFIC\n'


def test_custom_config_file_path(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test using a custom config file path."""
    input_path = tmp_path / 'input.ipynb'
    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

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
    """Test error when config file has invalid TOML."""
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text('[[files]\ninvalid toml')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'Invalid TOML' in result.stderr


def test_missing_required_field_input(tmp_path: Path, scrub_project):
    """Test error when file entry is missing required 'input' field."""
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
output = "{tmp_path / 'output.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'missing required field: input' in result.stderr


def test_missing_required_field_output(tmp_path: Path, scrub_project):
    """Test error when file entry is missing required 'output' field."""
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{tmp_path / 'input.ipynb'}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'missing required field: output' in result.stderr


def test_no_files_in_config(tmp_path: Path, scrub_project):
    """Test error when config has no file entries."""
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text("""
[options]
clear-tag = "scrub-clear"
""")

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'must contain at least one file entry' in result.stderr


def test_input_file_not_found(tmp_path: Path, scrub_project):
    """Test error when input file doesn't exist."""
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
    """Test error when input notebook has invalid JSON."""
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
    assert 'Invalid JSON' in result.stderr


def test_output_directory_creation(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test that output directories are created automatically."""
    input_path = tmp_path / 'input.ipynb'
    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

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
    assert output_path.parent.exists()


def test_relative_paths(tmp_path: Path, sample_notebook: Notebook, scrub_project):
    """Test using relative paths in config file."""
    input_dir = tmp_path / 'src'
    input_dir.mkdir()

    input_path = input_dir / 'notebook.ipynb'
    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text("""
[[files]]
input = "src/notebook.ipynb"
output = "dist/notebook.ipynb"
""")

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    assert (tmp_path / 'dist' / 'notebook.ipynb').exists()


def test_custom_tags_per_file(tmp_path: Path, scrub_project):
    """Test using different custom tags for different files."""
    # Create notebook with custom tag
    nb1 = {
        'cells': [
            {
                'cell_type': 'code',
                'source': 'solution code',
                'metadata': {'tags': ['solution']},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    # Create notebook with different custom tag
    nb2 = {
        'cells': [
            {
                'cell_type': 'code',
                'source': 'answer code',
                'metadata': {'tags': ['answer']},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    input1_path = tmp_path / 'input1.ipynb'
    input2_path = tmp_path / 'input2.ipynb'

    with input1_path.open('w') as f:
        json.dump(nb1, f)
    with input2_path.open('w') as f:
        json.dump(nb2, f)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input1_path}"
output = "{tmp_path / 'output1.ipynb'}"
clear-tag = "solution"

[[files]]
input = "{input2_path}"
output = "{tmp_path / 'output2.ipynb'}"
clear-tag = "answer"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0

    # Both notebooks should have their cells cleared with respective tags
    with (tmp_path / 'output1.ipynb').open() as f:
        nb1_out = json.load(f)
    with (tmp_path / 'output2.ipynb').open() as f:
        nb2_out = json.load(f)

    assert nb1_out['cells'][0]['source'] == '# TODO: Implement this\n'
    assert nb2_out['cells'][0]['source'] == '# TODO: Implement this\n'


def test_pyproject_toml(tmp_path: Path, sample_notebook: Notebook, scrub_project):
    """Test using pyproject.toml for configuration."""
    input_path = tmp_path / 'input.ipynb'
    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    # Create pyproject.toml with config
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
    assert (tmp_path / 'output.ipynb').exists()

    with (tmp_path / 'output.ipynb').open() as f:
        nb_out = json.load(f)

    # Check that pyproject.toml config was used
    assert nb_out['cells'][1]['source'] == '# FROM PYPROJECT\n'


def test_pyproject_without_ipynb_scrubber_section(tmp_path: Path, scrub_project):
    """Test error when pyproject.toml doesn't have ipynb-scrubber section."""
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


def test_discovery_from_subdirectory(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test config discovery from a subdirectory."""
    # Create structure: tmp_path/.ipynb-scrubber.toml and tmp_path/subdir/
    subdir = tmp_path / 'subdir'
    subdir.mkdir()

    input_path = tmp_path / 'input.ipynb'
    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    # Config in parent directory
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    # Run from subdirectory
    result = scrub_project(cwd=str(subdir))

    assert result.returncode == 0
    assert (tmp_path / 'output.ipynb').exists()


def test_discovery_prefers_standalone_over_pyproject(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test that .ipynb-scrubber.toml is preferred over pyproject.toml."""
    input_path = tmp_path / 'input.ipynb'
    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    # Create both config files with different clear text
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

    with (tmp_path / 'output.ipynb').open() as f:
        nb_out = json.load(f)

    # Should use standalone config
    assert nb_out['cells'][1]['source'] == '# FROM STANDALONE\n'


def test_no_config_found(tmp_path: Path, scrub_project):
    """Test error when no config file is found."""
    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'No config file found' in result.stderr


def test_explicit_config_bypasses_discovery(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test that --config-file bypasses discovery."""
    input_path = tmp_path / 'input.ipynb'
    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    # Create config in parent
    parent_config = tmp_path / '.ipynb-scrubber.toml'
    parent_config.write_text(f'''
[options]
clear-text = "# FROM PARENT"

[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    # Create specific config with different text
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

    with (tmp_path / 'output.ipynb').open() as f:
        nb_out = json.load(f)

    # Should use custom config, not discovered parent
    assert nb_out['cells'][1]['source'] == '# FROM CUSTOM\n'


def test_discovery_upward_multiple_levels(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test discovery searches upward through multiple directory levels."""
    # Create structure: tmp_path/a/b/c/ with config at tmp_path/
    deep_dir = tmp_path / 'a' / 'b' / 'c'
    deep_dir.mkdir(parents=True)

    input_path = tmp_path / 'input.ipynb'
    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    # Config at root
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
''')

    # Run from deeply nested directory
    result = scrub_project(cwd=str(deep_dir))

    assert result.returncode == 0
    assert (tmp_path / 'output.ipynb').exists()


def test_note_cells_with_notes_file(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test note cells with notes file specified."""
    input_path = tmp_path / 'input.ipynb'
    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    notes_file = tmp_path / 'notes.md'

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
notes-file = "{notes_file}"
''')

    # Add a note cell to the notebook
    sample_notebook['cells'].append(
        {
            'cell_type': 'code',
            'source': '#| scrub-note: note-1\ndef note_solution():\n    return "noted"',
            'metadata': {},
        },
    )

    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    assert notes_file.exists()

    # Check notes content with note ID
    notes_content = notes_file.read_text()
    assert '## note-1' in notes_content
    assert 'def note_solution():' in notes_content


def test_note_cells_without_notes_file_fails(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test that note cells without notes file cause error."""
    input_path = tmp_path / 'input.ipynb'

    # Add a note cell to the notebook with ID
    sample_notebook['cells'].append(
        {
            'cell_type': 'code',
            'source': (
                '#| scrub-note: error-test\ndef note_solution():\n    return "noted"'
            ),
            'metadata': {},
        },
    )

    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
# No notes-file specified
''')

    result = scrub_project(cwd=str(tmp_path))

    # Should fail with error
    assert result.returncode == 1
    assert 'note tag' in result.stderr
    assert 'no notes-file specified' in result.stderr


def test_multiple_files_with_notes(
    tmp_path: Path,
    sample_notebook: Notebook,
    scrub_project,
):
    """Test processing multiple files with different notes files."""
    # Create two notebooks
    input1_path = tmp_path / 'input1.ipynb'
    input2_path = tmp_path / 'input2.ipynb'

    nb1 = sample_notebook.copy()
    nb1['cells'].append(
        {
            'cell_type': 'code',
            'source': '#| scrub-note: nb1-note\ndef solution1():\n    return 1',
            'metadata': {},
        },
    )

    nb2 = sample_notebook.copy()
    nb2['cells'].append(
        {
            'cell_type': 'code',
            'source': '#| scrub-note: nb2-note\ndef solution2():\n    return 2',
            'metadata': {},
        },
    )

    with input1_path.open('w') as f:
        json.dump(nb1, f)
    with input2_path.open('w') as f:
        json.dump(nb2, f)

    notes1 = tmp_path / 'notes1.md'
    notes2 = tmp_path / 'notes2.md'

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[[files]]
input = "{input1_path}"
output = "{tmp_path / 'output1.ipynb'}"
notes-file = "{notes1}"

[[files]]
input = "{input2_path}"
output = "{tmp_path / 'output2.ipynb'}"
notes-file = "{notes2}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    assert notes1.exists()
    assert notes2.exists()

    # Check each notes file has the right note ID
    assert '## nb1-note' in notes1.read_text()
    assert 'solution1' in notes1.read_text()

    assert '## nb2-note' in notes2.read_text()
    assert 'solution2' in notes2.read_text()


def test_custom_note_tag(tmp_path: Path, sample_notebook: Notebook, scrub_project):
    """Test using a custom note tag."""
    input_path = tmp_path / 'input.ipynb'

    # Use custom tag with ID
    sample_notebook['cells'].append(
        {
            'cell_type': 'code',
            'source': (
                '#| solution-note: custom-id\ndef '
                'custom_solution():\n    return "custom"'
            ),
            'metadata': {},
        },
    )

    with input_path.open('w') as f:
        json.dump(sample_notebook, f)

    notes_file = tmp_path / 'notes.md'

    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text(f'''
[options]
note-tag = "solution-note"

[[files]]
input = "{input_path}"
output = "{tmp_path / 'output.ipynb'}"
notes-file = "{notes_file}"
''')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 0
    assert notes_file.exists()

    notes_content = notes_file.read_text()
    assert '## custom-id' in notes_content
    assert 'custom_solution' in notes_content
