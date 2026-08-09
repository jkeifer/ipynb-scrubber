"""Run configured scrubbing jobs: read notebooks, scrub them, write results."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from .exceptions import ScrubberError
from .notebook import get_notebook_language
from .notes import render_notes
from .processor import process_notebook
from .staging import StagedFile, commit, discard, stage

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path
    from typing import IO

    from .config import FileEntry


def _stage(final: Path, write_content: Callable[[IO[str]], None]) -> StagedFile:
    """Stage one output, reporting a write failure as a :class:`ScrubberError`.

    Raises:
        ScrubberError: If the output cannot be staged.
    """
    try:
        return stage(final, write_content)
    except OSError as e:
        raise ScrubberError(f'Error writing {final}: {e}') from e


def _commit_or_discard(staged: list[StagedFile]) -> None:
    """Move staged outputs into place, removing whatever is left if that fails.

    Raises:
        ScrubberError: If a staged output cannot be moved onto its target.
    """
    try:
        commit(staged)
    except OSError as e:
        raise ScrubberError(f'Error writing output: {e}') from e
    finally:
        # A committed file has been moved, so there is nothing left to remove
        # on the way out of a successful commit. Sweeping unconditionally is
        # what cleans up after one that failed or was interrupted partway.
        discard(staged)


def stage_file(entry: FileEntry) -> list[StagedFile]:
    """Scrub the notebook a config entry describes and stage its outputs.

    Reads ``entry.input``, scrubs it with ``entry.options``, and writes the
    exercise notebook and any notes to temporary files beside their targets.
    Neither ``entry.output`` nor ``entry.notes_file`` is touched until the
    returned staged files are passed to :func:`ipynb_scrubber.staging.commit`.

    Args:
        entry: A file entry carrying fully resolved scrubbing options.

    Returns:
        The entry's staged outputs, in the order they should be committed. A
        notes file is only meaningful alongside the exercise notebook it
        annotates, so the notebook comes first.

    Raises:
        ScrubberError: If the input is missing, unreadable or not a valid
            notebook, if notes were collected but the entry names no notes
            file, or if an output cannot be staged. Anything staged before the
            failure is removed.
    """
    if not entry.input.exists():
        raise ScrubberError(f'Input file not found: {entry.input}')

    try:
        with entry.input.open() as f:
            notebook = json.load(f)
    except json.JSONDecodeError as e:
        raise ScrubberError(f'Invalid JSON in {entry.input}: {e}') from e
    except OSError as e:
        raise ScrubberError(f'Error reading {entry.input}: {e}') from e

    processed_notebook, notes = process_notebook(notebook, entry.options)

    notes_file = entry.notes_file
    if notes and notes_file is None:
        raise ScrubberError(
            f'Found {len(notes)} cell(s) with note tag '
            f'"{entry.options.note_tag}", but no notes-file specified in config',
        )

    def write_notebook(stream: IO[str]) -> None:
        json.dump(processed_notebook, stream, indent=1)

    staged: list[StagedFile] = []
    try:
        staged.append(_stage(entry.output, write_notebook))

        if notes and notes_file is not None:
            content = render_notes(notes, get_notebook_language(processed_notebook))

            def write_notes(stream: IO[str]) -> None:
                stream.write(content)

            staged.append(_stage(notes_file, write_notes))
    except BaseException:
        discard(staged)
        raise

    return staged


def scrub_file(entry: FileEntry) -> None:
    """Scrub the notebook a config entry describes and write its outputs.

    Reads ``entry.input``, scrubs it with ``entry.options``, and writes the
    exercise notebook to ``entry.output`` and any notes to
    ``entry.notes_file``.

    Both outputs are staged beside their targets and moved into place only once
    both are written, so a failure anywhere leaves the targets as they were and
    neither file is ever observed half-written.

    Args:
        entry: A file entry carrying fully resolved scrubbing options.

    Raises:
        ScrubberError: If the input is missing, unreadable or not a valid
            notebook, if notes were collected but the entry names no notes
            file, or if an output cannot be written.
    """
    _commit_or_discard(stage_file(entry))


def scrub_files(entries: Iterable[FileEntry]) -> None:
    """Scrub every entry as a single all-or-nothing batch.

    Every entry's outputs are staged first, and the batch is committed only
    once all of them have staged successfully. A failure at any point removes
    every staged file, so the target tree keeps the contents it had.

    Committing is one rename per output rather than one transaction: no file is
    ever observed partially written, but a process that dies mid-commit can
    leave the earlier entries committed and the rest not.

    Args:
        entries: The file entries to scrub.

    Raises:
        ScrubberError: If any entry cannot be scrubbed or its outputs cannot be
            written. The message names the entry's input path.
    """
    staged: list[StagedFile] = []
    try:
        for entry in entries:
            try:
                staged.extend(stage_file(entry))
            except ScrubberError as e:
                raise ScrubberError(f'Error processing {entry.input}: {e}') from e
    except BaseException:
        discard(staged)
        raise

    _commit_or_discard(staged)
