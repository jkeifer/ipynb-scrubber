from __future__ import annotations

from dataclasses import dataclass

from .config import ScrubbingOptions
from .exceptions import ProcessingError
from .notebook import Cell, get_cell_source
from .options import Option, parse_cell_options


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


CellAction = Omit | Keep | Clear | Note


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
            raise ProcessingError(
                f"Option '{opts.note_tag}' has both inline text and a block; "
                'use one or the other',
            )
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
        raise ProcessingError(
            f'only one scrubber option per cell, but found {", ".join(present)}. '
            'If one of these was meant as block content, indent it more deeply '
            'than the option line that opens the block',
        )

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


def apply(cell: Cell, action: CellAction) -> Cell:
    """Apply a decided action to a cell, in place."""
    cell.pop('outputs', None)
    cell.pop('execution_count', None)

    match action:
        case Clear(text=text):
            cell['source'] = text
        case Note(note_id=note_id, text=text):
            suffix = f'\n{text}' if text else ''
            cell['source'] = f'# (See notes: {note_id}){suffix}'
        case Omit() | Keep():
            pass

    return cell
