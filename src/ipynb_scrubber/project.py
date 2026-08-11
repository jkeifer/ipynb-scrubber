"""Run configured scrubbing jobs: read notebooks, scrub them, write results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .exceptions import MissingNotesDestinationError, ScrubberError, reporting
from .notes import require_destination
from .processor import scrub
from .staging import commit_all, stage, staged_batch

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .config import FileEntry
    from .staging import StagedFile


def stage_file(entry: FileEntry, staged: list[StagedFile]) -> None:
    """Scrub the notebook an entry describes, appending its outputs to ``staged``.

    Nothing is written until ``staged`` is committed, and the notebook is
    appended before the notes file that is only meaningful alongside it.

    Raises:
        ScrubberError: On a bad input or a failed stage. Whatever was appended
            stays in ``staged``, for its owner to remove.
    """
    if not entry.input.exists():
        raise ScrubberError(f'Input file not found: {entry.input}')

    with reporting(f'Error reading {entry.input}'):
        data = entry.input.read_bytes()

    result = scrub(data, entry.options)

    notes_file = entry.notes_file
    try:
        require_destination(result.note_count, notes_file, entry.options.note_tag)
    except MissingNotesDestinationError as e:
        raise ScrubberError(f'{e} Set notes-file for this entry in the config.') from e

    with reporting(f'Error writing {entry.output}'):
        staged.append(stage(entry.output, result.notebook_text))

    if result.notes_text is not None and notes_file is not None:
        with reporting(f'Error writing {notes_file}'):
            staged.append(stage(notes_file, result.notes_text))


def scrub_files(entries: Iterable[FileEntry]) -> None:
    """Scrub every entry as a single all-or-nothing batch.

    Everything is staged before anything is committed, so a failure leaves the
    target tree as it was. Commit is not a transaction, though: a process dying
    partway can leave earlier entries committed.

    Raises:
        ScrubberError: If any entry cannot be scrubbed or written.
    """
    with staged_batch() as staged:
        for entry in entries:
            try:
                stage_file(entry, staged)
            except ScrubberError as e:
                raise ScrubberError(f'Error processing {entry.input}: {e}') from e

        with reporting('Error writing output'):
            commit_all(staged)
