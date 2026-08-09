import json

import pytest

from ipynb_scrubber.processor import Notebook


@pytest.fixture(scope='session')
def scrub_notebook(scrubber):
    def inner(*args: str, input_data: str | None = None, **kwargs):
        return scrubber('scrub-notebook', *args, input_data=input_data, **kwargs)

    return inner


def test_basic_functionality(scrub_notebook, basic_notebook: Notebook) -> None:
    result = scrub_notebook(
        input_data=json.dumps(basic_notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    # Check metadata was added
    assert output['metadata']['exercise_version'] is True

    # Check cells
    cells = output['cells']

    # First cell (markdown) should be unchanged
    assert cells[0]['cell_type'] == 'markdown'
    assert 'Test Notebook' in ''.join(cells[0]['source'])

    # Second cell (regular code) should have content but no outputs
    assert cells[1]['cell_type'] == 'code'
    assert 'Regular code cell' in ''.join(cells[1]['source'])
    assert 'outputs' not in cells[1]
    assert 'execution_count' not in cells[1]

    # Third cell (solution with tag) should be cleared
    assert cells[2]['cell_type'] == 'code'
    assert cells[2]['source'] == '# TODO: Implement this'
    assert 'outputs' not in cells[2]

    # Fourth cell (solution with Quarto option) should be cleared
    assert cells[3]['cell_type'] == 'code'
    assert cells[3]['source'] == '# TODO: Implement this'

    # Fifth cell (Quarto option false) should NOT be cleared
    assert cells[4]['cell_type'] == 'code'
    assert 'visible_code = True' in ''.join(cells[4]['source'])


def test_custom_tag(scrub_notebook, basic_notebook: Notebook) -> None:
    # Change tag to "answer"
    basic_notebook['cells'][2]['metadata']['tags'] = ['answer']  # type: ignore

    result = scrub_notebook(
        '--clear-tag',
        'answer',
        input_data=json.dumps(basic_notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    # Cell with "answer" tag should be cleared
    assert output['cells'][2]['source'] == '# TODO: Implement this'

    # Cell with Quarto "scrub-clear" option should NOT be cleared (different tag)
    assert 'another_solution' in ''.join(output['cells'][3]['source'])


def test_custom_todo_text(scrub_notebook, basic_notebook: Notebook) -> None:
    result = scrub_notebook(
        '--clear-text',
        '# YOUR CODE HERE',
        input_data=json.dumps(basic_notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    # Check cleared cells have custom text
    assert output['cells'][2]['source'] == '# YOUR CODE HERE'
    assert output['cells'][3]['source'] == '# YOUR CODE HERE'


def test_no_cells_to_clear(scrub_notebook):
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': "print('hello')",
                'outputs': [],
                'execution_count': 1,
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    # Cell should be unchanged except for cleared outputs
    assert output['cells'][0]['source'] == "print('hello')"
    assert 'outputs' not in output['cells'][0]
    assert 'execution_count' not in output['cells'][0]
    assert output['metadata']['exercise_version'] is True


def test_empty_notebook(scrub_notebook):
    notebook = {
        'cells': [],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    assert output['cells'] == []
    assert output['metadata']['exercise_version'] is True


def test_omit_tag(scrub_notebook):
    notebook = {
        'cells': [
            {
                'cell_type': 'markdown',
                'source': '# Keep this',
                'metadata': {},
            },
            {
                'cell_type': 'code',
                'source': "print('this should be omitted')",
                'metadata': {'tags': ['scrub-omit']},
            },
            {
                'cell_type': 'code',
                'source': "print('keep this')",
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    # Should only have 2 cells (omitted cell removed)
    assert len(output['cells']) == 2
    assert output['cells'][0]['source'] == '# Keep this'
    assert output['cells'][1]['source'] == "print('keep this')"


def test_omit_with_quarto(scrub_notebook):
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': "#| scrub-omit\nprint('omit me')",
                'metadata': {},
            },
            {
                'cell_type': 'code',
                'source': "print('keep me')",
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    assert len(output['cells']) == 1
    assert 'keep me' in output['cells'][0]['source']


def test_custom_omit_tag(scrub_notebook):
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': "print('remove')",
                'metadata': {'tags': ['remove-me']},
            },
            {
                'cell_type': 'code',
                'source': "print('keep')",
                'metadata': {'tags': ['scrub-omit']},  # Default tag should not work
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--omit-tag',
        'remove-me',
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    assert len(output['cells']) == 1
    assert output['cells'][0]['source'] == "print('keep')"


def test_omit_and_solution_tags(scrub_notebook):
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': '# Cell 1: normal',
                'metadata': {},
            },
            {
                'cell_type': 'code',
                'source': '# Cell 2: solution',
                'metadata': {'tags': ['scrub-clear']},
            },
            {
                'cell_type': 'code',
                'source': '# Cell 3: omit',
                'metadata': {'tags': ['scrub-omit']},
            },
            {
                'cell_type': 'code',
                'source': '# Cell 4: both tags',
                'metadata': {'tags': ['scrub-clear', 'scrub-omit']},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    # Should have 2 cells: normal and solution (cleared)
    assert len(output['cells']) == 2
    assert output['cells'][0]['source'] == '# Cell 1: normal'
    assert output['cells'][1]['source'] == '# TODO: Implement this'


def test_invalid_json_input(scrub_notebook):
    """Test handling of invalid JSON input."""
    result = scrub_notebook(
        input_data='{ invalid json',
    )

    assert result.returncode == 1
    assert 'Error: Invalid JSON input' in result.stderr


def test_missing_cells_field(scrub_notebook):
    """Test handling of notebook missing cells field."""
    notebook = {
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 1
    assert 'Error:' in result.stderr
    assert "missing required 'cells' field" in result.stderr


def test_invalid_cell_type(scrub_notebook):
    """Test handling of invalid cell type."""
    notebook = {
        'cells': [
            {
                'cell_type': 'invalid_type',
                'source': 'content',
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 1
    assert 'Error:' in result.stderr
    assert 'invalid cell_type' in result.stderr


def test_missing_cell_type(scrub_notebook):
    """Test handling of cell missing cell_type field."""
    notebook = {
        'cells': [
            {
                'source': 'content',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 1
    assert 'Error:' in result.stderr
    assert "missing required 'cell_type' field" in result.stderr


def test_quarto_custom_text(scrub_notebook):
    """Test Quarto clear tag with custom text."""
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': '#| scrub-clear: Custom replacement text\nprint("solution")',
                'metadata': {},
            },
            {
                'cell_type': 'code',
                'source': '#| scrub-clear: \nprint("empty text")',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    assert len(output['cells']) == 2
    assert output['cells'][0]['source'] == 'Custom replacement text'
    assert output['cells'][1]['source'] == ''


def test_markdown_cell_clearing(scrub_notebook):
    """Test clearing markdown cells with HTML comments and tags."""
    notebook = {
        'cells': [
            {
                'cell_type': 'markdown',
                'source': (
                    '<!-- scrub-clear: **Your answer here** '
                    '-->\n\n## Question 1\n\nWhat is the answer?'
                ),
                'metadata': {},
            },
            {
                'cell_type': 'markdown',
                'source': '## Question 2\n\nThis is an answer that should be cleared.',
                'metadata': {'tags': ['scrub-clear']},
            },
            {
                'cell_type': 'markdown',
                'source': (
                    '<!-- scrub-clear -->\n\n## Question 3\n\nAnother answer to clear.'
                ),
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    assert len(output['cells']) == 3
    assert output['cells'][0]['source'] == '**Your answer here**'
    assert output['cells'][1]['source'] == '# TODO: Implement this'
    assert output['cells'][2]['source'] == '# TODO: Implement this'


def test_raw_cell_clearing(scrub_notebook):
    """Test clearing raw cells with metadata tags only."""
    notebook = {
        'cells': [
            {
                'cell_type': 'raw',
                'source': '$$\\int_0^1 x^2 dx = \\frac{1}{3}$$',
                'metadata': {'tags': ['scrub-clear']},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    assert len(output['cells']) == 1
    assert output['cells'][0]['source'] == '# TODO: Implement this'


def test_note_cell_with_file(scrub_notebook, tmp_path):
    """Test note cells with notes file specified."""

    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': '#| scrub-note: exercise-1\ndef solution():\n    return 42',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    # Check notes file was created
    assert notes_file.exists()

    # Check note content with note ID
    notes_content = notes_file.read_text()
    assert '## exercise-1' in notes_content
    assert 'def solution():' in notes_content
    assert 'return 42' in notes_content

    # Check cell was cleared with reference comment
    assert output['cells'][0]['source'] == (
        '# (See notes: exercise-1)\n# TODO: Implement this'
    )


def test_note_cell_without_file_warns(scrub_notebook):
    """Test that note cells without notes file issue a warning."""
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': '#| scrub-note: test-note\ndef solution():\n    return 42',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    # Should succeed with warning
    assert result.returncode == 0

    # Check for warning in stderr
    assert 'scrub-note' in result.stderr
    assert 'no --notes-file specified' in result.stderr

    # Check cell was still cleared with reference
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == (
        '# (See notes: test-note)\n# TODO: Implement this'
    )


def test_note_cell_with_custom_replacement(scrub_notebook, tmp_path):
    """Test note cells with custom replacement text."""

    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': (
                    '#| scrub-note: my-note | '
                    '# YOUR CODE HERE\ndef solution():\n    return 42'
                ),
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)

    # Check custom replacement was used
    assert output['cells'][0]['source'] == ('# (See notes: my-note)\n# YOUR CODE HERE')

    # Check notes file
    notes_content = notes_file.read_text()
    assert '## my-note' in notes_content


@pytest.mark.parametrize(
    'source',
    [
        '#| scrub-note\ndef solution():\n    return 42',
        '#| scrub-note:\ndef solution():\n    return 42',
        '#| scrub-note: | # YOUR CODE HERE\ndef solution():\n    return 42',
        '#| scrub-note: |\n#|   # YOUR CODE HERE\ndef solution():\n    return 42',
    ],
)
def test_note_cell_without_id_errors(scrub_notebook, tmp_path, source):
    """A scrub-note without a usable id is an error, not a silent pass-through."""
    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {'cell_type': 'code', 'source': source, 'metadata': {}},
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 1
    assert 'Cell 0' in result.stderr
    assert 'requires an id' in result.stderr
    assert not notes_file.exists()


def test_note_cell_block_replacement(scrub_notebook, tmp_path):
    """A note's replacement text can come from a block."""
    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': (
                    '#| scrub-note: ex-1 |\n'
                    '#|   def add(a, b):\n'
                    '#|       pass\n'
                    'def add(a, b):\n'
                    '    return a + b'
                ),
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == (
        '# (See notes: ex-1)\ndef add(a, b):\n    pass'
    )
    assert '## ex-1' in notes_file.read_text()


def test_note_cell_block_opener_without_body(scrub_notebook, tmp_path):
    """A block opener with no body clears the cell to just the note reference."""
    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': '#| scrub-note: my-id |\ndef solution():\n    return 42',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == '# (See notes: my-id)'
    assert '## my-id' in notes_file.read_text()


@pytest.mark.parametrize(
    'source',
    [
        '#| scrub-note: ex-1|# YOUR CODE HERE\nprint("x")',
        '#| scrub-note: ex-1 |# YOUR CODE HERE\nprint("x")',
        '#| scrub-note: ex-1 | # YOUR CODE HERE\nprint("x")',
    ],
)
def test_note_separator_is_whitespace_insensitive(scrub_notebook, tmp_path, source):
    """The id/replacement split is on the first pipe, regardless of spacing."""
    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {'cell_type': 'code', 'source': source, 'metadata': {}},
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == ('# (See notes: ex-1)\n# YOUR CODE HERE')


def test_note_cell_non_code_errors(scrub_notebook, tmp_path):
    """A note tag on a non-code cell is a hard error, not a silent no-op."""
    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {
                'cell_type': 'markdown',
                'source': '<!-- scrub-note: md-note -->\n## Solution',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 1
    assert 'Cell 0' in result.stderr
    assert 'only supported on code cells' in result.stderr
    assert not notes_file.exists()


def test_note_cell_inline_text_with_block_errors(scrub_notebook, tmp_path):
    """A note with both inline replacement text and a block is a hard error."""
    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': (
                    '#| scrub-note: ex-1 | # TODO |\n'
                    '#|   # YOUR CODE HERE\n'
                    'def solution():\n'
                    '    return 42'
                ),
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 1
    assert 'Cell 0' in result.stderr
    assert 'both inline text and a block' in result.stderr
    assert not notes_file.exists()


def test_note_cell_id_then_block_is_not_an_error(scrub_notebook, tmp_path):
    """An id with a bare block opener is the ordinary multi-line note form."""
    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': (
                    '#| scrub-note: ex-1 |\n'
                    '#|   # YOUR CODE HERE\n'
                    'def solution():\n'
                    '    return 42'
                ),
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == ('# (See notes: ex-1)\n# YOUR CODE HERE')
    assert '## ex-1' in notes_file.read_text()


def test_note_cell_inline_text_without_block_is_not_an_error(scrub_notebook, tmp_path):
    """Inline replacement text with no block remains the ordinary inline form."""
    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': (
                    '#| scrub-note: ex-1 | # TODO\ndef solution():\n    return 42'
                ),
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == '# (See notes: ex-1)\n# TODO'
    assert '## ex-1' in notes_file.read_text()


def test_note_absent_on_markdown_cell_is_fine(scrub_notebook, tmp_path):
    """A markdown cell without a note option is untouched by the note check."""
    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {
                'cell_type': 'markdown',
                'source': '## Solution',
                'metadata': {},
            },
            {
                'cell_type': 'raw',
                'source': '#| scrub-note: raw-note\nraw content',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == '## Solution'
    assert output['cells'][1]['source'] == '#| scrub-note: raw-note\nraw content'


def test_code_cell_multiline_block(scrub_notebook):
    """Multi-line replacement via a block scalar in a code cell."""
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': (
                    '#| scrub-clear: |\n'
                    '#|   def add(a, b):\n'
                    '#|       # TODO: your code here\n'
                    '#|       pass\n'
                    'def add(a, b):\n'
                    '    return a + b'
                ),
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(input_data=json.dumps(notebook))

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == (
        'def add(a, b):\n    # TODO: your code here\n    pass'
    )


def test_markdown_cell_multiline_block(scrub_notebook):
    """Multi-line replacement via a block scalar in a markdown cell."""
    notebook = {
        'cells': [
            {
                'cell_type': 'markdown',
                'source': (
                    '<!-- scrub-clear: |\n'
                    '  **Write your answer here**\n'
                    '\n'
                    '  Show your work.\n'
                    '-->\n'
                    '## Solution'
                ),
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(input_data=json.dumps(notebook))

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == (
        '**Write your answer here**\n\nShow your work.'
    )


def test_inline_escape_sequences(scrub_notebook):
    """Escapes are expanded in inline values."""
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': '#| scrub-clear: line one\\nline two\nprint("x")',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(input_data=json.dumps(notebook))

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == 'line one\nline two'


def test_inline_text_with_block_errors(scrub_notebook):
    """Inline text plus a block is a hard error."""
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': '#| scrub-clear: some text |\n#|   more text\nprint("x")',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(input_data=json.dumps(notebook))

    assert result.returncode == 1
    assert 'Cell 0' in result.stderr
    assert 'both inline text and a block' in result.stderr


def test_unterminated_markdown_block_errors(scrub_notebook):
    """An unterminated markdown block is a hard error naming the cell."""
    notebook = {
        'cells': [
            {'cell_type': 'markdown', 'source': '# Intro', 'metadata': {}},
            {
                'cell_type': 'markdown',
                'source': '<!-- scrub-clear: |\n  never closed',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(input_data=json.dumps(notebook))

    assert result.returncode == 1
    assert 'Cell 1' in result.stderr
    assert 'Unterminated' in result.stderr


def test_multiline_clear_text_cli(scrub_notebook):
    """A multi-line --clear-text value survives to the output."""
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': 'def add(a, b):\n    return a + b',
                'metadata': {'tags': ['scrub-clear']},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--clear-text',
        'def add(a, b):\n    # TODO\n    pass',
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['cells'][0]['source'] == 'def add(a, b):\n    # TODO\n    pass'


@pytest.mark.parametrize(
    ('cell_type', 'source'),
    [
        ('code', 'def solution():\n    return 42'),
        ('markdown', '## Solution\n\nThe answer is 42.'),
        ('raw', 'raw solution content'),
    ],
)
def test_note_metadata_tag_errors(scrub_notebook, tmp_path, cell_type, source):
    """The note tag as Jupyter cell metadata is a hard error, never a no-op."""
    notes_file = tmp_path / 'notes.md'

    notebook = {
        'cells': [
            {
                'cell_type': cell_type,
                'source': source,
                'metadata': {'tags': ['scrub-note']},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--notes-file',
        str(notes_file),
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 1
    assert 'Cell 0' in result.stderr
    assert 'not supported as a cell tag' in result.stderr
    assert source not in result.stdout
    assert not notes_file.exists()


def test_note_metadata_tag_with_custom_tag_errors(scrub_notebook):
    """The error follows a custom --note-tag rather than the default name."""
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': 'def solution():\n    return 42',
                'metadata': {'tags': ['keepme']},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(
        '--note-tag',
        'keepme',
        input_data=json.dumps(notebook),
    )

    assert result.returncode == 1
    assert "Option 'keepme' is not supported as a cell tag" in result.stderr


def test_omit_metadata_tag_beats_note_metadata_tag(scrub_notebook):
    """A cell tagged both omit and note is omitted, not an error."""
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': 'def solution():\n    return 42',
                'metadata': {'tags': ['scrub-omit', 'scrub-note']},
            },
            {
                'cell_type': 'code',
                'source': 'print("kept")',
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = scrub_notebook(input_data=json.dumps(notebook))

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert len(output['cells']) == 1
    assert output['cells'][0]['source'] == 'print("kept")'
