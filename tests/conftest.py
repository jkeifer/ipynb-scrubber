import functools
import subprocess
import sys

import pytest

from tests import builders


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


#: The builders are plain functions in builders.py; these fixtures only expose
#: them to the tests already written to request them as parameters.
@pytest.fixture
def make_notebook():
    return builders.make_notebook


@pytest.fixture
def code():
    return builders.code


@pytest.fixture
def markdown():
    return builders.markdown


@pytest.fixture
def raw():
    return builders.raw
