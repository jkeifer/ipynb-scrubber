import functools
import subprocess
import sys

import pytest

from ipynb_scrubber.processor import Notebook


@pytest.fixture(scope='session')
def scrubber():
    def inner(
        *args: str,
        input_data: str | None = None,
        **kwargs,
    ):
        cmd = [sys.executable, '-m', 'ipynb_scrubber.cli']
        cmd.extend(args)

        kwargs['input'] = input_data
        kwargs['capture_output'] = True
        kwargs['text'] = True

        return subprocess.run(
            cmd,
            **kwargs,
        )

    return inner


@pytest.fixture
def scrub_notebook(scrubber):
    return functools.partial(scrubber, 'scrub-notebook')


@pytest.fixture
def scrub_project(scrubber):
    return functools.partial(scrubber, 'scrub-project')


@pytest.fixture
def make_notebook():
    """Build a notebook from cell dicts, filling in the boilerplate."""

    def inner(*cells: dict, metadata: dict | None = None) -> Notebook:
        return {
            'cells': [{'metadata': {}, **cell} for cell in cells],
            'metadata': {} if metadata is None else metadata,
            'nbformat': 4,
            'nbformat_minor': 4,
        }

    return inner


@pytest.fixture
def code():
    """Build a code cell."""
    return lambda source, **kw: {'cell_type': 'code', 'source': source, **kw}


@pytest.fixture
def markdown():
    """Build a markdown cell."""
    return lambda source, **kw: {'cell_type': 'markdown', 'source': source, **kw}


@pytest.fixture
def raw():
    """Build a raw cell."""
    return lambda source, **kw: {'cell_type': 'raw', 'source': source, **kw}


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
                    '#| scrub-clear\n',
                    '# Solution cell with Quarto option\n',
                    'def another_solution():\n',
                    '    return "hidden"',
                ],
            },
            {
                'cell_type': 'code',
                'metadata': {},
                'source': [
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
