"""Write output files through a staging area, so no half-written result exists.

Content goes to a temporary file in the target's own directory and is moved onto
the target with :meth:`pathlib.Path.replace`. The temporary file must live in
that directory because a rename is atomic only within a single filesystem; a
reader then sees either the prior contents or the complete new contents.

Committing several files is several renames, not one transaction, so an
interruption mid-commit can leave some targets updated and others not. Each
individual file is still whole.
"""

from __future__ import annotations

import contextlib
import tempfile

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

#: Mode for a staged file whose target does not exist. Temporary files are
#: created owner-only, which is wrong for an ordinary output file.
DEFAULT_FILE_MODE = 0o644

#: Everything this tool writes is UTF-8, never the locale's encoding: a notebook
#: is UTF-8 by specification and notes are extracted from one.
ENCODING = 'utf-8'


@dataclass(frozen=True)
class StagedFile:
    """A fully written temporary file and the path it is destined for."""

    temp: Path
    final: Path


def stage(final: Path, content: str) -> StagedFile:
    """Write the content destined for ``final`` to a temporary file beside it.

    ``final``'s directory is created if missing, and its mode is taken if it
    exists.

    Raises:
        OSError: If the directory or temporary file cannot be written.
    """
    final.parent.mkdir(parents=True, exist_ok=True)

    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding=ENCODING,
            newline='',
            dir=final.parent,
            prefix=f'.{final.name}.',
            suffix='.tmp',
            delete=False,
        ) as f:
            temp = Path(f.name)
            f.write(content)
        temp.chmod(
            final.stat().st_mode & 0o777 if final.exists() else DEFAULT_FILE_MODE,
        )
    except BaseException:
        if temp is not None:
            temp.unlink(missing_ok=True)
        raise

    return StagedFile(temp=temp, final=final)


def _commit(staged: Iterable[StagedFile]) -> None:
    """The rename half of :func:`commit_all`, without the cleanup."""
    for item in staged:
        item.temp.replace(item.final)


def discard(staged: Iterable[StagedFile]) -> None:
    """Remove staged temporary files, leaving their target paths alone.

    Safe after a partial commit and safe to repeat; removal errors are
    suppressed, since a discard runs in response to a more interesting failure.
    """
    for item in staged:
        with contextlib.suppress(OSError):
            item.temp.unlink(missing_ok=True)


def commit_all(staged: Iterable[StagedFile]) -> None:
    """Rename every staged file onto its target, then sweep up unconditionally.

    Raises:
        OSError: If a staged file cannot be moved onto its target.
    """
    items = list(staged)
    try:
        _commit(items)
    finally:
        discard(items)


@contextlib.contextmanager
def staged_batch() -> Iterator[list[StagedFile]]:
    """Collect staged files, removing them all if the block does not finish.

    Cleanup runs for any exception, :class:`KeyboardInterrupt` included;
    committing the yielded batch is the caller's job.
    """
    staged: list[StagedFile] = []
    try:
        yield staged
    except BaseException:
        discard(staged)
        raise
