from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, assert_never

from .config import ScrubbingOptions, reject_unknown_keys
from .exceptions import ProcessingError, ScrubberError
from .notebook import Cell, get_cell_source, to_cell_source
from .options import Header, Option, parse_cell_options


@dataclass(frozen=True)
class Omit:
    """Drop the cell from the output entirely."""


@dataclass(frozen=True)
class Keep:
    """Leave the cell's source untouched."""


@dataclass(frozen=True)
class Clear:
    """Replace the cell's source with ``text``, below any ``header`` kept."""

    text: str
    header: str = ''


@dataclass(frozen=True)
class Note:
    """Save ``body`` under ``note_id`` and replace the cell's source with ``text``.

    ``body`` is the cell's content with its option header removed. The header
    is an instruction to this tool, and one carrying ``text`` holds the very
    scaffolding the student is meant to fill in, so keeping it would file the
    exercise prompt alongside the answer it is a prompt for.
    """

    note_id: str
    text: str
    body: str
    header: str = ''


#: What can happen to a cell that survives into the output. ``apply`` accepts
#: exactly these, so "an omitted cell is never rewritten" is a type, not a
#: comment.
CellRewrite = Keep | Clear | Note

CellAction = Omit | CellRewrite


def _replacement_text(name: str, value: Any, default: str) -> str:
    """The replacement text an option carries; ``default`` when it carries none.

    YAML resolves an unquoted value to a type, so a value that is not text is
    reported rather than rendered: ``scrub-clear: no`` is a boolean, and
    clearing a cell to ``False`` is never what the author meant.

    Raises:
        ProcessingError: If the value is present but is not text.
    """
    if value is None:
        return default
    if not isinstance(value, str):
        raise ProcessingError(
            f"Option '{name}' takes replacement text, but got {value!r}. "
            'Quote the value to use it as text',
        )
    return value


def _note_id(value: Any, opts: ScrubbingOptions) -> str:
    """The note id from a ``scrub-note`` scalar or its mapping's ``id``.

    Raises:
        ProcessingError: If the id is missing, empty, or not text.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ProcessingError(
        f"Option '{opts.note_tag}' requires an id, e.g. '{opts.note_tag}: exercise-1'",
    )


def _note_action(
    value: Any,
    opts: ScrubbingOptions,
    body: str,
    kept: str,
) -> Note:
    """Build the Note described by a ``scrub-note`` option's value.

    The value is either the note id on its own, or a mapping carrying ``id``
    and an optional ``text`` to leave in the cleared cell.

    Raises:
        ProcessingError: If the id is unusable, the text is not a string, or
            the mapping carries a key the option does not define.
    """
    if not isinstance(value, dict):
        return Note(_note_id(value, opts), opts.clear_text, body, kept)

    try:
        reject_unknown_keys(value, ('id', 'text'), f'{opts.note_tag} key')
    except ScrubberError as e:
        raise ProcessingError(str(e)) from e

    return Note(
        _note_id(value.get('id'), opts),
        _replacement_text(
            f'{opts.note_tag}.text',
            value.get('text'),
            opts.clear_text,
        ),
        body,
        kept,
    )


def _scrubber_options(opts: ScrubbingOptions) -> tuple[Option, ...]:
    """The options this tool defines, under their configured spellings.

    ``takes_text`` is what tells the parser whose values a YAML comment could
    silently eat. ``scrub-omit`` carries no value, so it has none to lose.
    """
    return (
        Option(opts.clear_tag, takes_text=True),
        Option(opts.omit_tag, takes_text=False),
        Option(opts.note_tag, takes_text=True),
    )


def _check_one_scrubber_option(
    header: Header,
    options: Collection[Option],
) -> None:
    """Require the header to carry no more than one scrubber option.

    Under-indented block content is a sibling option as far as YAML is
    concerned, and reading it as one would silently delete a cell, so the
    ambiguity is refused. When one of the options present opens a block, the
    message names it, because that is the line the content belongs under.

    Raises:
        ProcessingError: If more than one scrubber option is present.
    """
    present = sorted(
        {option.name for option in options} & header.options.keys(),
    )
    if len(present) < 2:
        return

    message = f'only one scrubber option per cell, but found {", ".join(present)}.'
    openers = sorted(header.block_styled.intersection(present))
    if openers:
        message += (
            f" If one of these was meant as content of '{openers[0]}', indent "
            "it more deeply than that option's line"
        )
    raise ProcessingError(message)


def _under_header(kept: str, content: str) -> str:
    """``content`` with the header lines the cell keeps restored above it.

    A cell's option header is shared, so the lines carrying somebody else's
    options survive a rewrite: they configure the cell that remains, not the
    content this tool replaced.

    Everything kept goes above the replacement, whatever order it sat in
    relative to the option that was removed. That is not a tidying choice: a
    ``#|`` run is only read as options where it is, at the very top of the
    cell. An option written back below the replacement would be an ordinary
    comment, and would quietly stop doing anything at all.
    """
    return f'{kept}\n{content}' if kept else content


def _default_clear_text(cell_type: str, opts: ScrubbingOptions) -> str:
    """The replacement text for a cleared cell whose author supplied none.

    A placeholder has to read as the kind of cell it lands in. The code default
    is a comment, and dropping a comment into a markdown cell renders it as a
    heading rather than as the note to the student it is meant to be.
    """
    return opts.clear_text_markdown if cell_type == 'markdown' else opts.clear_text


def _omit_action(value: Any, opts: ScrubbingOptions) -> Omit:
    """Build the Omit a ``scrub-omit`` option describes.

    Presence is the whole signal the option carries, so a value means the
    author expected something the option cannot do.

    Raises:
        ProcessingError: If the option carries a value.
    """
    if value is not None:
        raise ProcessingError(
            f"Option '{opts.omit_tag}' takes no value, but got {value!r}",
        )
    return Omit()


def decide(cell: Cell, opts: ScrubbingOptions) -> CellAction:
    """Decide what happens to a cell.

    This is the single place that answers that question.

    A cell's source header may carry at most one scrubber option; two is an
    error, because an under-indented block content line is indistinguishable
    from a sibling option and silently deleting a cell is the worse outcome.
    Metadata tags are not subject to that rule.

    A tag carries presence and nothing else, which is exactly what an option
    written with no value carries, so the two spellings merge into one mapping
    and a single precedence order covers both. The header wins where both name
    the same option, and the order is the documented one: omit, then note, then
    clear.

    Raises:
        ProcessingError: If the cell's options are malformed, misplaced, or
            ambiguous.
    """
    tags: list[str] = cell.get('metadata', {}).get('tags', [])
    cell_type = cell.get('cell_type', '')
    source = get_cell_source(cell)
    scrubber_options = _scrubber_options(opts)
    header = parse_cell_options(cell_type, source, scrubber_options)

    _check_one_scrubber_option(header, scrubber_options)

    cell_options: dict[str, Any] = {**dict.fromkeys(tags), **header.options}

    if opts.omit_tag in cell_options:
        return _omit_action(cell_options[opts.omit_tag], opts)

    if opts.note_tag in tags:
        raise ProcessingError(
            f"Option '{opts.note_tag}' is not supported as a cell tag; "
            f"write '#| {opts.note_tag}: <id>' in a code cell's source",
        )

    if opts.note_tag in cell_options:
        if cell_type != 'code':
            raise ProcessingError(
                f"Option '{opts.note_tag}' is only supported on code cells",
            )
        return _note_action(
            cell_options[opts.note_tag],
            opts,
            header.body,
            header.kept,
        )

    if opts.clear_tag in cell_options:
        return Clear(
            _replacement_text(
                opts.clear_tag,
                cell_options[opts.clear_tag],
                _default_clear_text(cell_type, opts),
            ),
            header.kept,
        )

    return Keep()


def _without_results(cell: Cell) -> Cell:
    """A copy of ``cell`` carrying none of the results of having been run.

    A code cell's ``outputs`` and ``execution_count`` are *required* by the
    nbformat schema, so they are emptied rather than removed: a cell missing
    them fails validation, and a notebook that fails validation is a notebook
    some tool downstream will refuse. Any other cell type must not carry them at
    all, so there they are dropped.

    The copy is shallow, and that is provably enough: every key touched is
    rebound to a fresh value rather than mutated in place, and the outputs a
    deep copy would have duplicated are exactly what is being discarded.
    """
    updated: Cell = {**cell}

    if updated.get('cell_type') == 'code':
        updated['outputs'] = []
        updated['execution_count'] = None
    else:
        updated.pop('outputs', None)
        updated.pop('execution_count', None)

    return updated


def apply(cell: Cell, action: CellRewrite) -> Cell:
    """Return a new cell with ``action`` applied; ``cell`` is left alone.

    ``Omit`` is not accepted: an omitted cell has no output form, so the
    caller drops it rather than asking for one.
    """
    updated = _without_results(cell)

    match action:
        case Keep():
            return updated
        case Clear(text=text, header=kept):
            source = _under_header(kept, text)
        case Note(note_id=note_id, text=text, header=kept):
            suffix = f'\n{text}' if text else ''
            source = _under_header(kept, f'# (See notes: {note_id}){suffix}')
        case _:
            assert_never(action)

    updated['source'] = to_cell_source(cell, source)
    return updated
