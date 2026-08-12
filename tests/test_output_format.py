"""What the bytes on disk look like.

These are the guarantees a reader of the output depends on but that no
assertion about the in-memory notebook can catch: that the result still
validates against the nbformat schema, that it survives a round trip through
a machine whose locale is not UTF-8, and that it is diffable against what
Jupyter itself would have written.
"""

import json
import subprocess
import sys

import nbformat
import pytest

from ipynb_scrubber.config import FileEntry
from ipynb_scrubber.notebook import dumps_notebook
from ipynb_scrubber.options import ScrubbingOptions
from ipynb_scrubber.processor import process_notebook
from ipynb_scrubber.project import scrub_files

# These tests read the bytes, so they build the schema-valid shape: a cell id,
# and outputs/execution_count on every code cell. See builders.py.
from tests.builders import markdown, schema_valid_code, schema_valid_notebook

OPTS = ScrubbingOptions()

ACCENTED = 'x = "café ☕ naïve ünïcødé"'


@pytest.mark.parametrize(
    ('label', 'source'),
    [
        ('kept', 'x = 1'),
        ('cleared', '#| scrub-clear:\nsecret()'),
        ('noted', '#| scrub-note: ex-1\nsecret()'),
    ],
)
def test_output_validates_against_the_nbformat_schema(label, source):
    """A code cell's outputs and execution_count are required by the schema.

    Removing them rather than emptying them produced a notebook that any tool
    validating its input would reject.
    """
    nb = schema_valid_notebook(
        schema_valid_code(
            source,
            outputs=[{'output_type': 'stream', 'name': 'stdout', 'text': 'hi'}],
            execution_count=3,
        ),
    )
    result, _ = process_notebook(nb, OPTS)

    nbformat.validate(nbformat.from_dict(result))


def test_markdown_output_validates_against_the_nbformat_schema():
    """A markdown cell must NOT carry run results, so there they are dropped."""
    nb = schema_valid_notebook(
        markdown('<!-- scrub-clear: -->\nanswer', id='m'),
    )
    result, _ = process_notebook(nb, OPTS)

    nbformat.validate(nbformat.from_dict(result))


def test_a_rewritten_cell_keeps_the_line_list_shape_jupyter_writes():
    """Otherwise one scrubbed cell becomes a single very long line in the diff."""
    nb = schema_valid_notebook(
        schema_valid_code(['#| scrub-clear:\n', 'secret()'], id='a'),
        schema_valid_code(['x = 1\n', 'y = 2'], id='b'),
    )
    result, _ = process_notebook(nb, OPTS)

    assert result['cells'][0]['source'] == [OPTS.clear_text]
    assert result['cells'][1]['source'] == ['x = 1\n', 'y = 2']


def test_serialization_does_not_escape_non_ascii():
    """Jupyter writes ensure_ascii=False; escaping is lossless but unreadable."""
    text = dumps_notebook(schema_valid_notebook(schema_valid_code(ACCENTED)))

    assert 'café ☕ naïve ünïcødé' in text
    assert '\\u00e9' not in text


def test_serialization_ends_with_a_newline():
    assert dumps_notebook(schema_valid_notebook(schema_valid_code('x = 1'))).endswith(
        '}\n',
    )


def test_serialization_is_indented_the_way_jupyter_indents():
    assert '\n "cells"' in dumps_notebook(
        schema_valid_notebook(schema_valid_code('x = 1')),
    )


def test_non_ascii_survives_a_file_round_trip(tmp_path):
    source = tmp_path / 'in.ipynb'
    source.write_bytes(
        json.dumps(
            schema_valid_notebook(schema_valid_code(ACCENTED)),
            ensure_ascii=False,
        ).encode('utf-8'),
    )
    out = tmp_path / 'out.ipynb'

    scrub_files([FileEntry(input=source, output=out)])

    assert json.loads(out.read_bytes())['cells'][0]['source'] == ACCENTED


def test_non_ascii_survives_an_ascii_locale(tmp_path):
    """The notebook's encoding is the notebook's, not the locale's.

    Reading or writing through the locale default turned any notebook holding
    an accent into a UnicodeDecodeError on a machine set to a non-UTF-8 locale,
    which is the default in many CI containers.
    """
    source = tmp_path / 'in.ipynb'
    source.write_bytes(
        json.dumps(
            schema_valid_notebook(schema_valid_code(ACCENTED)),
            ensure_ascii=False,
        ).encode('utf-8'),
    )
    out = tmp_path / 'out.ipynb'
    script = (
        'from ipynb_scrubber.config import FileEntry\n'
        'from ipynb_scrubber.project import scrub_files\n'
        'from pathlib import Path\n'
        f'scrub_files([FileEntry(input=Path({str(source)!r}), '
        f'output=Path({str(out)!r}))])\n'
    )

    result = subprocess.run(
        [sys.executable, '-c', script],
        capture_output=True,
        text=True,
        env={
            'LC_ALL': 'C',
            'LANG': 'C',
            'PYTHONUTF8': '0',
            'PYTHONCOERCECLOCALE': '0',
            'PATH': '/usr/bin:/bin',
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_bytes())['cells'][0]['source'] == ACCENTED


def test_stdin_and_stdout_are_utf8_regardless_of_locale():
    """The CLI reads and writes bytes, so a piped notebook is not re-encoded."""
    nb = schema_valid_notebook(schema_valid_code(ACCENTED))
    result = subprocess.run(
        [sys.executable, '-m', 'ipynb_scrubber.cli', 'scrub-notebook'],
        input=json.dumps(nb, ensure_ascii=False).encode('utf-8'),
        capture_output=True,
        env={
            'LC_ALL': 'C',
            'LANG': 'C',
            'PYTHONUTF8': '0',
            'PYTHONCOERCECLOCALE': '0',
            'PATH': '/usr/bin:/bin',
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
    assert json.loads(result.stdout)['cells'][0]['source'] == ACCENTED
    assert 'café'.encode() in result.stdout
