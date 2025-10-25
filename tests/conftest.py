import json
import subprocess
import sys

import pytest

from ipynb_scrubber.processor import Notebook


@pytest.fixture(scope='session')
def scrubber():
    def inner(
        *args: str,
        input_data: str | None = None,
    ):
        cmd = [sys.executable, '-m', 'ipynb_scrubber.cli']
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

    return inner


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
