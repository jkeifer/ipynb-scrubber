import json
import subprocess
import sys

import pytest

from ipynb_scrubber.processor import Notebook


def run_scrubber(input_data, args=None):
    cmd = [sys.executable, '-m', 'ipynb_scrubber.cli']
    if args:
        cmd.extend(args)

    result = subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f'Command failed: {result.stderr}')

    return json.loads(result.stdout)


@pytest.fixture
def basic_notebook() -> Notebook:
    return {
        'cells': [
            {
                'cell_type': 'markdown',
                'metadata': {},
                'source': [
                    '# Test Notebook\n',
                    '\n',
                    'This notebook tests the ipynb-scrubber functionality.',
                ],
            },
            {
                'cell_type': 'code',
                'execution_count': 1,
                'metadata': {},
                'source': [
                    '# Regular code cell\n',
                    'print("This is a regular cell")',
                ],
                'outputs': [
                    {
                        'name': 'stdout',
                        'output_type': 'stream',
                        'text': ['This is a regular cell\n'],
                    },
                ],
            },
            {
                'cell_type': 'code',
                'execution_count': 2,
                'metadata': {'tags': ['scrub-clear']},
                'source': [
                    '# Solution cell with tag\n',
                    'def secret_solution():\n',
                    '    return 42\n',
                    '\n',
                    'secret_solution()',
                ],
                'outputs': [
                    {
                        'data': {'text/plain': ['42']},
                        'execution_count': 2,
                        'metadata': {},
                        'output_type': 'execute_result',
                    },
                ],
            },
            {
                'cell_type': 'code',
                'metadata': {},
                'source': [
                    '#| scrub-clear: true\n',
                    '# Solution cell with Quarto option\n',
                    'def another_solution():\n',
                    '    return "hidden"',
                ],
            },
            {
                'cell_type': 'code',
                'metadata': {},
                'source': [
                    '#| scrub-clear: false\n',
                    '# This should NOT be cleared\n',
                    'visible_code = True',
                ],
            },
            {
                'cell_type': 'markdown',
                'metadata': {},
                'source': [
                    '## Another section\n',
                    '\n',
                    'More content here.',
                ],
            },
        ],
        'metadata': {
            'kernelspec': {
                'display_name': 'Python 3',
                'language': 'python',
                'name': 'python3',
            },
            'language_info': {
                'name': 'python',
                'version': '3.8.0',
            },
        },
        'nbformat': 4,
        'nbformat_minor': 4,
    }


def test_basic_functionality(basic_notebook: Notebook) -> None:
    output = run_scrubber(json.dumps(basic_notebook))

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


def test_custom_tag(basic_notebook: Notebook) -> None:
    # Change tag to "answer"
    basic_notebook['cells'][2]['metadata']['tags'] = ['answer']  # type: ignore

    output = run_scrubber(json.dumps(basic_notebook), ['--clear-tag', 'answer'])

    # Cell with "answer" tag should be cleared
    assert output['cells'][2]['source'] == '# TODO: Implement this\n'

    # Cell with Quarto "scrub-clear" option should NOT be cleared (different tag)
    assert 'another_solution' in ''.join(output['cells'][3]['source'])


def test_custom_todo_text(basic_notebook: Notebook) -> None:
    output = run_scrubber(
        json.dumps(basic_notebook),
        ['--clear-text', '# YOUR CODE HERE'],
    )

    # Check cleared cells have custom text
    assert output['cells'][2]['source'] == '# YOUR CODE HERE\n'
    assert output['cells'][3]['source'] == '# YOUR CODE HERE\n'


def test_no_cells_to_clear():
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

    output = run_scrubber(json.dumps(notebook))

    # Cell should be unchanged except for cleared outputs
    assert output['cells'][0]['source'] == "print('hello')"
    assert 'outputs' not in output['cells'][0]
    assert 'execution_count' not in output['cells'][0]
    assert output['metadata']['exercise_version'] is True


def test_empty_notebook():
    notebook = {
        'cells': [],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    output = run_scrubber(json.dumps(notebook))

    assert output['cells'] == []
    assert output['metadata']['exercise_version'] is True


def test_omit_tag():
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

    output = run_scrubber(json.dumps(notebook))

    # Should only have 2 cells (omitted cell removed)
    assert len(output['cells']) == 2
    assert output['cells'][0]['source'] == '# Keep this'
    assert output['cells'][1]['source'] == "print('keep this')"


def test_omit_with_quarto():
    notebook = {
        'cells': [
            {
                'cell_type': 'code',
                'source': "#| scrub-omit: true\nprint('omit me')",
                'metadata': {},
            },
            {
                'cell_type': 'code',
                'source': "#| scrub-omit: false\nprint('keep me')",
                'metadata': {},
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }

    output = run_scrubber(json.dumps(notebook))

    assert len(output['cells']) == 1
    assert 'keep me' in output['cells'][0]['source']


def test_custom_omit_tag():
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

    output = run_scrubber(json.dumps(notebook), ['--omit-tag', 'remove-me'])

    assert len(output['cells']) == 1
    assert output['cells'][0]['source'] == "print('keep')"


def test_omit_and_solution_tags():
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

    output = run_scrubber(json.dumps(notebook))

    # Should have 2 cells: normal and solution (cleared)
    assert len(output['cells']) == 2
    assert output['cells'][0]['source'] == '# Cell 1: normal'
    assert output['cells'][1]['source'] == '# TODO: Implement this\n'


def test_invalid_json_input():
    """Test handling of invalid JSON input."""
    result = subprocess.run(
        [sys.executable, '-m', 'ipynb_scrubber.cli'],
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
        [sys.executable, '-m', 'ipynb_scrubber.cli'],
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
        [sys.executable, '-m', 'ipynb_scrubber.cli'],
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
        [sys.executable, '-m', 'ipynb_scrubber.cli'],
        input=json.dumps(notebook),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert 'Error:' in result.stderr
    assert "missing required 'cell_type' field" in result.stderr
