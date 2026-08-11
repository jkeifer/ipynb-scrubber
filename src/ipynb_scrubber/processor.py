"""Turn a notebook into its exercise version: in memory, and end to end."""

import json

from dataclasses import dataclass
from typing import Any

from .actions import Note, Omit, Scrubber, ScrubbingOptions
from .exceptions import ProcessingError, ScrubberError
from .notebook import (
    Cell,
    Notebook,
    dumps_notebook,
    empty_like,
    evolve,
    get_notebook_language,
    loads_notebook,
    validate_notebook,
)
from .notes import render_notes


def process_notebook(
    notebook: Any,
    scrub_options: ScrubbingOptions,
) -> tuple[Notebook, dict[str, str]]:
    """Process a notebook to create an exercise version.

    The input is left untouched, and the result comes back with a mapping of
    note_id -> original source.

    Raises:
        InvalidNotebookError: If the notebook structure is invalid
        ProcessingError: If an error occurs during processing
    """
    validated = validate_notebook(notebook)
    scrubber = Scrubber.for_options(scrub_options)

    # note_id -> (index of the cell that claimed it, that cell's source)
    notes: dict[str, tuple[int, str]] = {}
    processed: list[Cell] = []

    for index, cell in enumerate(validated['cells']):
        try:
            action = scrubber.decide(cell)

            if isinstance(action, Omit):
                continue

            if isinstance(action, Note):
                claimed_by = notes.get(action.note_id)
                if claimed_by is not None:
                    raise ProcessingError(
                        f"Duplicate note id '{action.note_id}'; already used "
                        f'by cell {claimed_by[0]}. Note ids '
                        'must be unique within a notebook',
                    )
                notes[action.note_id] = (index, action.body)

            processed.append(scrubber.apply(cell, action))
        except ScrubberError as e:
            raise ProcessingError(f'Cell {index}: {e}') from e

    # The default is validated's own class, not a dict literal, so a notebook
    # with no metadata key still comes back with metadata in its own class --
    # the invariant this module holds is total, with no exception for an
    # absent key.
    metadata = validated.get('metadata', empty_like(validated))
    # The changes target Notebook, a TypedDict, so they are typed as one and
    # unpacked -- rather than passed as keywords -- to get mypy's key and
    # value-type checking back; evolve's **changes: Any would otherwise wave
    # a misspelled key or a wrong value through unchecked. The inner
    # evolve(metadata, ...) call targets a plain dict[str, Any], which an
    # annotated changes mapping would not check either way, so it stays a
    # keyword argument.
    changes: Notebook = {
        'cells': processed,
        'metadata': evolve(metadata, exercise_version=True),
    }
    result = evolve(validated, **changes)
    return result, {note_id: source for note_id, (_, source) in notes.items()}


@dataclass(frozen=True)
class NotebookScrubResult:
    """Everything scrubbing one in-memory notebook produces.

    The notebook is an object rather than text because a caller holding one has
    its serializer to hand already -- and it comes back in the class it went in
    as, so a notebook parsed by jupytext can be written by jupytext.
    """

    #: The exercise notebook, in the class the input notebook arrived as. Every
    #: copy in the pipeline is shallow, so a part this run left untouched --
    #: a cell it did not rewrite, its metadata -- is the same object as in the
    #: input notebook; mutating it here reaches back into that input too.
    notebook: Notebook
    #: The rendered notes document, or None if no cell carried the note tag.
    notes_text: str | None
    #: How many cells were noted, so a caller with nowhere to put the notes can
    #: say how many it is refusing to throw away.
    note_count: int

    def to_text(self) -> 'ScrubResult':
        """This result with its notebook serialized the way Jupyter writes one.

        The one road from the object form to the text form, so that a caller
        that took the object form to keep a class alive can still end up with
        exactly what :func:`scrub` returns -- and so that the aliasing the
        notebook carries stops here rather than reaching a caller holding text.
        """
        return ScrubResult(
            notebook_text=dumps_notebook(self.notebook),
            notes_text=self.notes_text,
            note_count=self.note_count,
        )


def scrub_parsed(
    notebook: Any,
    options: ScrubbingOptions,
) -> NotebookScrubResult:
    """Scrub one already-parsed notebook: process it, and render its notes.

    The whole pipeline bar the parsing and the serializing, for a caller
    holding a notebook object rather than bytes -- one read by jupytext or
    nbformat, or built in memory. It comes back in the class it went in as, so
    ``jupytext.reads()`` and ``jupytext.writes()`` sit either side of this
    without a conversion between. Callers holding the bytes want :func:`scrub`,
    which is this with a JSON reader and writer on either end.

    Neither jupytext nor nbformat is a dependency of this package; both are
    simply callers this works for.

    Raises:
        ScrubberError: On a bad notebook or an unhonorable option header.
    """
    processed, notes = process_notebook(notebook, options)

    return NotebookScrubResult(
        notebook=processed,
        notes_text=(
            render_notes(notes, get_notebook_language(processed)) if notes else None
        ),
        note_count=len(notes),
    )


@dataclass(frozen=True)
class ScrubResult:
    """Everything scrubbing one notebook produces, as text ready to be written."""

    #: The exercise notebook, serialized the way Jupyter writes one.
    notebook_text: str
    #: The rendered notes document, or None if no cell carried the note tag.
    notes_text: str | None
    #: How many cells were noted, so a caller with nowhere to put the notes can
    #: say how many it is refusing to throw away.
    note_count: int


def scrub(data: bytes, options: ScrubbingOptions) -> ScrubResult:
    """Scrub one notebook, from input bytes to the text of every output.

    The whole pipeline both commands run; it touches no files, so its errors
    describe the notebook rather than the source.

    Raises:
        ScrubberError: On a bad notebook or an unhonorable option header.
    """
    try:
        notebook = loads_notebook(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # Both bad input, and so worth a friendly error rather than a traceback.
        raise ScrubberError(f'Invalid notebook JSON: {e}') from e

    return scrub_parsed(notebook, options).to_text()
