from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from .config import ScrubbingOptions
from .exceptions import ProcessingError
from .notebook import Cell, get_cell_source
from .options import Option, inline_plus_block_message, parse_cell_options


@dataclass(frozen=True)
class Omit:
    """Drop the cell from the output entirely."""


@dataclass(frozen=True)
class Keep:
    """Leave the cell's source untouched."""


@dataclass(frozen=True)
class Clear:
    """Replace the cell's source with ``text``."""

    text: str


@dataclass(frozen=True)
class Note:
    """Save the cell's source under ``note_id`` and replace it with ``text``."""

    note_id: str
    text: str


#: What can happen to a cell that survives into the output. ``apply`` accepts
#: exactly these, so "an omitted cell is never rewritten" is a type, not a
#: comment.
CellRewrite = Keep | Clear | Note

CellAction = Omit | CellRewrite


def _note_action(option: Option, opts: ScrubbingOptions) -> Note:
    fields = option.fields(2)
    note_id = fields[0] if fields else ''
    if not note_id:
        raise ProcessingError(
            f"Option '{opts.note_tag}' requires an id, "
            f"e.g. '{opts.note_tag}: exercise-1'",
        )

    inline_replacement = fields[1] if len(fields) > 1 else None

    if option.block is not None:
        if inline_replacement:
            raise ProcessingError(inline_plus_block_message(opts.note_tag))
        return Note(note_id, option.block)

    if inline_replacement is not None:
        return Note(note_id, inline_replacement)
    return Note(note_id, opts.clear_text)


def decide(cell: Cell, opts: ScrubbingOptions) -> CellAction:
    """Decide what happens to a cell.

    This is the single place that answers that question.

    A cell's source header may carry at most one scrubber option; two is an
    error, because an under-indented block content line is indistinguishable
    from a sibling option and silently deleting a cell is the worse outcome.
    Metadata tags are not subject to that rule, so the documented
    omit-tag-beats-note-tag precedence still applies via guard order.

    Raises:
        ProcessingError: If the cell's options are malformed, misplaced, or
            ambiguous.
    """
    tags: list[str] = cell.get('metadata', {}).get('tags', [])
    cell_options = parse_cell_options(
        cell.get('cell_type', ''),
        get_cell_source(cell),
    )

    scrubber_names = {opts.clear_tag, opts.omit_tag, opts.note_tag}
    present = sorted(scrubber_names & cell_options.keys())
    if len(present) > 1:
        message = f'only one scrubber option per cell, but found {", ".join(present)}.'
        if any(cell_options[name].block is not None for name in present):
            message += (
                ' If one of these was meant as block content, indent it more '
                'deeply than the option line that opens the block'
            )
        raise ProcessingError(message)

    if opts.omit_tag in tags or opts.omit_tag in cell_options:
        return Omit()

    if opts.note_tag in tags:
        raise ProcessingError(
            f"Option '{opts.note_tag}' is not supported as a cell tag; "
            f"write '#| {opts.note_tag}: <id>' in a code cell's source",
        )

    note = cell_options.get(opts.note_tag)
    if note is not None:
        if cell.get('cell_type', '') != 'code':
            raise ProcessingError(
                f"Option '{opts.note_tag}' is only supported on code cells",
            )
        return _note_action(note, opts)

    clear = cell_options.get(opts.clear_tag)
    if clear is not None:
        text = clear.single_text()
        return Clear(opts.clear_text if text is None else text)
    if opts.clear_tag in tags:
        return Clear(opts.clear_text)

    return Keep()


def apply(cell: Cell, action: CellRewrite) -> Cell:
    """Return a new cell with ``action`` applied; ``cell`` is left alone.

    The copy is shallow, and that is provably enough: the only keys touched
    are dropped outright ('outputs', 'execution_count') or rebound to a fresh
    string ('source'). Nothing still shared with the input is mutated, and the
    outputs a deep copy would have duplicated are exactly what gets discarded.

    ``Omit`` is not accepted: an omitted cell has no output form, so the
    caller drops it rather than asking for one.
    """
    updated: Cell = {**cell}
    updated.pop('outputs', None)
    updated.pop('execution_count', None)

    match action:
        case Keep():
            pass
        case Clear(text=text):
            updated['source'] = text
        case Note(note_id=note_id, text=text):
            suffix = f'\n{text}' if text else ''
            updated['source'] = f'# (See notes: {note_id}){suffix}'
        case _:
            assert_never(action)

    return updated
