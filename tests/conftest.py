import functools
import subprocess
import sys

import pytest

from ipynb_scrubber.notebook import Notebook


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
