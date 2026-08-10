"""Run configured scrubbing jobs: read notebooks, scrub them, write results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .exceptions import MissingNotesDestinationError, ScrubberError
from .notes import require_destination
from .processor import scrub
from .staging import StagedFile, commit_all, discard, stage

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from .config import FileEntry


def _stage(final: Path, content: str) -> StagedFile:
    """Stage one output, reporting a write failure as a :class:`ScrubberError`.

    Raises:
        ScrubberError: If the output cannot be staged.
    """
    try:
        return stage(final, content)
    except OSError as e:
        raise ScrubberError(f'Error writing {final}: {e}') from e


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
        data = entry.input.read_bytes()
    except OSError as e:
        raise ScrubberError(f'Error reading {entry.input}: {e}') from e

    result = scrub(data, entry.options)

    notes_file = entry.notes_file
    try:
        require_destination(result.note_count, notes_file, entry.options.note_tag)
    except MissingNotesDestinationError as e:
        raise ScrubberError(f'{e} Set notes-file for this entry in the config.') from e

    staged: list[StagedFile] = []
    try:
        staged.append(_stage(entry.output, result.notebook_text))

        if result.notes_text is not None and notes_file is not None:
            staged.append(_stage(notes_file, result.notes_text))
    except BaseException:
        discard(staged)
        raise

    return staged


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

    try:
        commit_all(staged)
    except OSError as e:
        raise ScrubberError(f'Error writing output: {e}') from e
