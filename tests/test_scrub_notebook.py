import json
import subprocess
import sys

import pytest

from ipynb_scrubber.processor import Notebook


@pytest.fixture(scope='session')
def scrub_notebook(scrubber):
    def inner(*args: str, input_data: str | None = None):
        return scrubber('scrub-notebook', *args, input_data=input_data)

    return inner


def test_basic_functionality(scrub_notebook, basic_notebook: Notebook) -> None:
    output = scrub_notebook(
        input_data=json.dumps(basic_notebook),
    )

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
    assert cells[2]['source'] == '# TODO: Implement this\n'
    assert 'outputs' not in cells[2]

    # Fourth cell (solution with Quarto option) should be cleared
    assert cells[3]['cell_type'] == 'code'
    assert cells[3]['source'] == '# TODO: Implement this\n'

    # Fifth cell (Quarto option false) should NOT be cleared
    assert cells[4]['cell_type'] == 'code'
    assert 'visible_code = True' in ''.join(cells[4]['source'])


def test_custom_tag(scrub_notebook, basic_notebook: Notebook) -> None:
    # Change tag to "answer"
    basic_notebook['cells'][2]['metadata']['tags'] = ['answer']  # type: ignore

    output = scrub_notebook(
        '--clear-tag',
        'answer',
        input_data=json.dumps(basic_notebook),
    )

    # Cell with "answer" tag should be cleared
    assert output['cells'][2]['source'] == '# TODO: Implement this\n'

    # Cell with Quarto "scrub-clear" option should NOT be cleared (different tag)
    assert 'another_solution' in ''.join(output['cells'][3]['source'])


def test_custom_todo_text(scrub_notebook, basic_notebook: Notebook) -> None:
    output = scrub_notebook(
        '--clear-text',
        '# YOUR CODE HERE',
        input_data=json.dumps(basic_notebook),
    )

    # Check cleared cells have custom text
    assert output['cells'][2]['source'] == '# YOUR CODE HERE\n'
    assert output['cells'][3]['source'] == '# YOUR CODE HERE\n'


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

    output = scrub_notebook(
        input_data=json.dumps(notebook),
    )

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

    output = scrub_notebook(
        input_data=json.dumps(notebook),
    )

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

    output = scrub_notebook(
        input_data=json.dumps(notebook),
    )

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

    output = scrub_notebook(
        input_data=json.dumps(notebook),
    )

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

    output = scrub_notebook(
        '--omit-tag',
        'remove-me',
        input_data=json.dumps(notebook),
    )

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

    output = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    # Should have 2 cells: normal and solution (cleared)
    assert len(output['cells']) == 2
    assert output['cells'][0]['source'] == '# Cell 1: normal'
    assert output['cells'][1]['source'] == '# TODO: Implement this\n'


def test_invalid_json_input():
    """Test handling of invalid JSON input."""
    result = subprocess.run(
        [sys.executable, '-m', 'ipynb_scrubber.cli', 'scrub-notebook'],
        input='{ invalid json',
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert 'Error: Invalid JSON input' in result.stderr


def test_missing_cells_field():
    """Test handling of notebook missing cells field."""
    notebook = {
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    result = subprocess.run(
        [sys.executable, '-m', 'ipynb_scrubber.cli', 'scrub-notebook'],
        input=json.dumps(notebook),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert 'Error:' in result.stderr
    assert "missing required 'cells' field" in result.stderr


def test_invalid_cell_type():
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

    result = subprocess.run(
        [sys.executable, '-m', 'ipynb_scrubber.cli', 'scrub-notebook'],
        input=json.dumps(notebook),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert 'Error:' in result.stderr
    assert 'invalid cell_type' in result.stderr


def test_missing_cell_type():
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

    result = subprocess.run(
        [sys.executable, '-m', 'ipynb_scrubber.cli', 'scrub-notebook'],
        input=json.dumps(notebook),
        capture_output=True,
        text=True,
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

    output = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert len(output['cells']) == 2
    assert output['cells'][0]['source'] == 'Custom replacement text\n'
    assert output['cells'][1]['source'] == '\n'


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

    output = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert len(output['cells']) == 3
    assert output['cells'][0]['source'] == '**Your answer here**\n'
    assert output['cells'][1]['source'] == '# TODO: Implement this\n'
    assert output['cells'][2]['source'] == '# TODO: Implement this\n'


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

    output = scrub_notebook(
        input_data=json.dumps(notebook),
    )

    assert len(output['cells']) == 1
    assert output['cells'][0]['source'] == '# TODO: Implement this\n'
