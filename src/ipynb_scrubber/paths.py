"""When two paths name one file, however differently each was spelled."""

from __future__ import annotations

import os
import stat

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Hashable

#: What a path names when nothing on disk answers to it. Kept distinct from a
#: real file's identity so that a path which exists and one which does not can
#: never compare equal, whatever their spellings.
_ABSENT = 'absent'


def identity(path: Path) -> Hashable:
    """A value two paths share exactly when they name one file.

    Asked of the filesystem wherever it can answer, because only the
    filesystem knows: a difference of case is a difference of file on one
    machine and not on another, and no comparison of spellings can tell which.
    That is also what sees through ``..`` and through a symlink.

    A path with nothing behind it yet has no inode to be asked about, so its
    resolved spelling stands in. That still catches ``..`` and a symlinked
    parent; it cannot catch a difference of case, which needs a file to exist
    before the question has an answer. Two outputs are usually both absent,
    and an output colliding with an input -- the case that destroys work -- is
    a collision with a file that does exist.
    """
    try:
        info = path.stat()
    except OSError:
        return (_ABSENT, path.resolve())
    return (info.st_dev, info.st_ino)


def stream_identity(fileno: int) -> Hashable | None:
    """The identity of the file open on ``fileno``, if it is a file at all.

    ``None`` for a pipe, a terminal, or anything else no path could name, so a
    caller comparing a path against a redirected stream gets an answer only
    when there is one to give.
    """
    try:
        info = os.fstat(fileno)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    return (info.st_dev, info.st_ino)
