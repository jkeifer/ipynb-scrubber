"""Finding and loading the project config, end to end through the CLI.

Which file ``scrub-project`` reads is decided before any notebook is touched:
an upward search from the process cwd, a preference between the two file names
that search recognises, and an explicit ``--config-file`` that skips the search
altogether. Every test here asserts about *which* config won, so each one that
succeeds writes an option value into the output that names its source.

What happens to the notebooks once a config is loaded lives in
tests/test_batch_atomicity.py.
"""

import json

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from tests.builders import code, make_notebook


@pytest.fixture
def sample_notebook():
    """A notebook with a clear-tagged and an omit-tagged cell.

    Cell 1 is the clear-tagged one, so ``cells[1]['source']`` in an output is
    whichever ``clear-text`` the winning config supplied.
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


def write(path: Path, notebook: Mapping[str, Any]) -> None:
    """Serialize a notebook to ``path``.

    Typed as a Mapping rather than a dict because the builders return the
    ``Notebook`` TypedDict, which is a Mapping but not a ``dict[Any, Any]``.
    """
    path.write_text(json.dumps(notebook))


# Discovery: what the upward search finds


def test_standalone_config_options_apply_globally_and_per_file(
    tmp_path: Path,
    sample_notebook,
    scrub_project,
):
    """A discovered .ipynb-scrubber.toml supplies both levels of option.

    The global [options] table reaches an entry that says nothing, and an entry
    that does say something wins over it -- the resolution ProjectConfig does
    in memory, seen in the bytes two different outputs end up holding.
    """
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

    nb1_out = json.loads((tmp_path / 'exercises' / 'lesson1.ipynb').read_text())
    nb2_out = json.loads((tmp_path / 'exercises' / 'lesson2.ipynb').read_text())

    assert nb1_out['cells'][1]['source'] == '# GLOBAL DEFAULT'
    assert nb2_out['cells'][1]['source'] == '# FILE SPECIFIC'


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


def test_no_config_found(tmp_path: Path, scrub_project):
    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'No config file found' in result.stderr


# --config-file: the search that does not happen


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


def test_pyproject_without_ipynb_scrubber_section(tmp_path: Path, scrub_project):
    """Named explicitly, a pyproject.toml with no section for us is an error.

    The search may skip such a file and keep climbing; a path the user typed
    has no higher place to go, so it has to say why it was no use.
    """
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


# A config that is found but cannot be loaded


def test_invalid_toml(tmp_path: Path, scrub_project):
    config_path = tmp_path / '.ipynb-scrubber.toml'
    config_path.write_text('[[files]\ninvalid toml')

    result = scrub_project(cwd=str(tmp_path))

    assert result.returncode == 1
    assert 'Invalid TOML' in result.stderr
