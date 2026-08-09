"""Write output files through a staging area, so no half-written result exists.

Content destined for a path is written to a temporary file in that path's own
directory and moved onto the target with :meth:`pathlib.Path.replace`, a
rename. Keeping the temporary file in the target's directory matters: a rename
is atomic only within a single filesystem. A reader therefore sees either the target's
prior contents or the complete new contents.

The guarantee stops there. Committing several files is several renames rather
than one transaction, so an interruption partway through a multi-file commit
can leave some targets updated and others not. Each individual file is still
whole.
"""

from __future__ import annotations

import contextlib
import tempfile

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import IO

#: Mode given to a staged file whose target does not already exist. A
#: temporary file is created readable only by its owner, which is wrong for an
#: ordinary output file.
DEFAULT_FILE_MODE = 0o644


@dataclass(frozen=True)
class StagedFile:
    """A fully written temporary file and the path it is destined for."""

    temp: Path
    final: Path


def stage(final: Path, write_content: Callable[[IO[str]], None]) -> StagedFile:
    """Write the content destined for ``final`` to a temporary file beside it.

    The temporary file is created in ``final``'s own directory, which is
    created if it does not exist, so that :func:`commit` can move it into place
    with an atomic rename. Nothing at ``final`` is touched.

    The staged file takes ``final``'s mode if ``final`` exists, and
    :data:`DEFAULT_FILE_MODE` otherwise.

    Args:
        final: The path the content is destined for.
        write_content: Callable that writes the whole content to a text stream.

    Returns:
        The staged file, to hand to :func:`commit` or :func:`discard`.

    Raises:
        OSError: If the directory or the temporary file cannot be created or
            written.
        Exception: Whatever ``write_content`` raises, after removing the
            temporary file.
    """
    final.parent.mkdir(parents=True, exist_ok=True)

    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=final.parent,
            prefix=f'.{final.name}.',
            suffix='.tmp',
            delete=False,
        ) as f:
            temp = Path(f.name)
            write_content(f)
        temp.chmod(
            final.stat().st_mode & 0o777 if final.exists() else DEFAULT_FILE_MODE,
        )
    except BaseException:
        if temp is not None:
            temp.unlink(missing_ok=True)
        raise

    return StagedFile(temp=temp, final=final)


def commit(staged: Iterable[StagedFile]) -> None:
    """Move every staged file onto its target path.

    Each move is a single rename, so no target is ever observed
    partially written. The moves happen one after another rather than as one
    transaction: if one fails, or the process dies partway through, the targets
    moved so far are updated and the rest are not.

    Args:
        staged: The staged files to commit, in the order they should appear.

    Raises:
        OSError: If a staged file cannot be moved onto its target.
    """
    for item in staged:
        item.temp.replace(item.final)


def discard(staged: Iterable[StagedFile]) -> None:
    """Remove staged temporary files, leaving their target paths alone.

    Anything :func:`commit` already moved is skipped, so discarding after a
    partial commit removes only what is still staged. An error removing a
    temporary file is suppressed: a discard runs in response to some other
    failure, and that failure is the one worth reporting.

    Args:
        staged: The staged files to remove.
    """
    for item in staged:
        with contextlib.suppress(OSError):
            item.temp.unlink(missing_ok=True)


def write_atomic(final: Path, write_content: Callable[[IO[str]], None]) -> None:
    """Write ``final`` in its entirety or not at all.

    Stages the content beside ``final`` and commits it, removing the temporary
    file if anything goes wrong.

    Args:
        final: The path to write.
        write_content: Callable that writes the whole content to a text stream.

    Raises:
        OSError: If the content cannot be written or moved into place.
        Exception: Whatever ``write_content`` raises.
    """
    item = stage(final, write_content)
    try:
        commit([item])
    finally:
        # A committed file has been moved, so there is nothing left to remove
        # on the way out of a successful commit. Sweeping unconditionally is
        # what cleans up after one that failed or was interrupted.
        discard([item])
