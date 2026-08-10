import functools
import subprocess
import sys

import pytest


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
