import functools
import subprocess
import sys

from pathlib import Path

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


@pytest.fixture
def failing_commit(monkeypatch):
    """Make moving a staged file onto its target fail.

    Patches the rename itself rather than commit_all, so commit_all's cleanup
    still runs -- that cleanup is what the tests using this are checking.
    """

    def boom(self, target):
        raise OSError('rename failed')

    monkeypatch.setattr(Path, 'replace', boom)
