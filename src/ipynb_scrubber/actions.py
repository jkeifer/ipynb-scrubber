from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Self, assert_never

from .exceptions import ProcessingError, ScrubberError
from .notebook import Cell, get_cell_source, to_cell_source
from .options import (
    Header,
    Option,
    is_plain_name,
    parse_cell_options,
    reads_back_as_text,
)
from .validation import reject_unknown_keys, reject_wrong_type


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

    ``body`` drops the cell's own option header: one carrying ``text`` holds the
    scaffolding the student must fill in, so filing it alongside the answer
    would give the exercise away.
    """

    note_id: str
    text: str
    body: str
    header: str = ''


#: What can happen to a cell that survives into the output. ``apply`` accepts
#: exactly these, so "an omitted cell is never rewritten" is a type.
CellRewrite = Keep | Clear | Note

CellAction = Omit | CellRewrite


@dataclass(frozen=True)
class ScrubbingOptions:
    """Scrubbing options.

    Frozen because every rule lives in ``__post_init__`` and nothing re-checks
    a field afterwards; derive copies with ``merged_with`` or
    ``dataclasses.replace``, which re-run those rules.
    """

    clear_tag: str = 'scrub-clear'
    clear_text: str = '# TODO: Implement this'
    clear_text_markdown: str = '*TODO: Implement this*'
    omit_tag: str = 'scrub-omit'
    note_tag: str = 'scrub-note'

    def __post_init__(self) -> None:
        """Reject values of the wrong type, and tag names unusable or colliding.

        A tag must round-trip through YAML as the same plain text, which the
        pattern alone does not ensure: ``yes``/``no`` resolve to booleans and
        ``null`` to nothing. Such a tag arrives off a header as a bool or None,
        no lookup by name finds it, and the cell ships unscrubbed -- for
        ``omit-tag``, with the solution in it. Tags must also be distinct, since
        equal spellings collapse and one behaviour vanishes.

        Raises:
            ScrubberError: On a wrong type, an unusable name, or duplicate tags.
        """
        for option in OPTIONS:
            reject_wrong_type(option.key, getattr(self, option.field), option.type)

        named = {
            option.key: getattr(self, option.field)
            for option in OPTIONS
            if option.build is not None
        }

        for key, name in named.items():
            if not is_plain_name(name):
                raise ScrubberError(
                    f'{key} must start with a letter and contain only letters, '
                    f'digits, hyphens and underscores, but got {name!r}',
                )
            if not reads_back_as_text(name):
                raise ScrubberError(
                    f'{key} must be a name YAML reads back as text, but got '
                    f'{name!r}, which YAML resolves to another type. Words like '
                    'yes, no, on, off, true, false and null are not names',
                )

        tags = tuple(named.values())
        if len(set(tags)) != len(tags):
            keys = ', '.join(named)
            spellings = ', '.join(f'{key}={name!r}' for key, name in named.items())
            raise ScrubberError(
                f'{keys} must all be distinct, but got {spellings}',
            )

    def merged_with(self, data: dict[str, Any]) -> Self:
        """Return a copy with every option ``data`` mentions overridden.

        Presence decides, not truthiness: a present key is used verbatim.

        Raises:
            ScrubberError: On a wrong-typed override or duplicate merged tags.
        """
        return replace(
            self,
            **{
                option.field: data[option.key]
                for option in OPTIONS
                if option.key in data
            },
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create ScrubbingOptions from a config mapping.

        Raises:
            ScrubberError: On an unknown key, wrong type, or duplicate tags.
        """
        reject_unknown_keys(data, [option.key for option in OPTIONS], 'option')
        return cls().merged_with(data)


@dataclass(frozen=True)
class _Marked:
    """A cell an option was found on, as the builders below need to see it."""

    scrubber: Scrubber
    cell_type: str
    #: Names carried as metadata tags, so a builder can tell which spelling
    #: its option arrived in.
    tags: frozenset[str]
    header: Header


#: How an option's value becomes the action it describes.
_Build = Callable[[Any, _Marked], CellAction]


def _replacement_text(name: str, value: Any, default: str) -> str:
    """The replacement text an option carries; ``default`` when it carries none.

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


def _note_id(name: str, value: Any) -> str:
    """``value`` as the id a note is filed under, trimmed of its whitespace.

    Raises:
        ProcessingError: If the id is missing, empty, or not text.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ProcessingError(
        f"Option '{name}' requires an id, e.g. '{name}: exercise-1'",
    )


def _note_action(value: Any, marked: _Marked) -> Note:
    """Build the Note a ``scrub-note`` describes.

    The option carries a note id, or a mapping of ``id`` and optional ``text``.

    Raises:
        ProcessingError: On a metadata tag (nowhere to put the id), a non-code
            cell, an unusable id, or non-string text.
        ScrubberError: On an undefined key.
    """
    opts = marked.scrubber.opts

    if opts.note_tag in marked.tags:
        raise ProcessingError(
            f"Option '{opts.note_tag}' is not supported as a cell tag; "
            f"write '#| {opts.note_tag}: <id>' in a code cell's source",
        )

    if marked.cell_type != 'code':
        raise ProcessingError(
            f"Option '{opts.note_tag}' is only supported on code cells",
        )

    body = marked.header.body
    kept = marked.header.kept

    if not isinstance(value, dict):
        return Note(_note_id(opts.note_tag, value), opts.clear_text, body, kept)

    reject_unknown_keys(value, ('id', 'text'), f'{opts.note_tag} key')

    return Note(
        _note_id(opts.note_tag, value.get('id')),
        _replacement_text(
            f'{opts.note_tag}.text',
            value.get('text'),
            opts.clear_text,
        ),
        body,
        kept,
    )


def _check_one_scrubber_option(header: Header, names: frozenset[str]) -> None:
    """Require the header to carry no more than one scrubber option.

    The reason is that under-indented block content is a sibling option as far
    as YAML is concerned.

    Raises:
        ProcessingError: If more than one scrubber option is present.
    """
    present = sorted(names & header.options.keys())
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

    Kept lines always go above the replacement, whatever their original order: a
    ``#|`` run is only read as options at the very top of the cell, so one
    written back below would become an ordinary comment and stop doing anything.
    """
    return f'{kept}\n{content}' if kept else content


def _omit_action(value: Any, marked: _Marked) -> Omit:
    """Build the Omit a ``scrub-omit`` option describes.

    Raises:
        ProcessingError: If the option carries a value.
    """
    if value is not None:
        raise ProcessingError(
            f"Option '{marked.scrubber.opts.omit_tag}' takes no value, "
            f'but got {value!r}',
        )
    return Omit()


def _clear_action(value: Any, marked: _Marked) -> Clear:
    """Build the Clear a ``scrub-clear`` option describes.

    Raises:
        ProcessingError: If the value is present but is not text.
    """
    return Clear(
        _replacement_text(
            marked.scrubber.opts.clear_tag,
            value,
            marked.scrubber.default_clear_text(marked.cell_type),
        ),
        marked.header.kept,
    )


@dataclass(frozen=True)
class ScrubberOption:
    """One option this tool defines, declared whole.

    That is: how a config file and the CLI spell it, which
    :class:`ScrubbingOptions` field holds a run's value for it, and -- for the
    options that mark cells -- what a cell carrying it becomes. Carrying a
    ``build`` is what makes an option a cell marker, so ``takes_text`` is read
    for those and nowhere else.
    """

    #: TOML key, and the CLI flag spelled ``--<key>``.
    key: str
    field: str
    type: type
    help: str
    takes_text: bool = False
    build: _Build | None = None


#: Every option this tool defines, in the order a cell's own options are
#: considered in: omit first because dropping a cell subsumes every rewrite of
#: it, and note before clear because a note is a clear that also files away what
#: it removed. The options carrying no builder mark no cell, so that order never
#: reaches them and they sit with the option whose replacement text they are.
OPTIONS: tuple[ScrubberOption, ...] = (
    ScrubberOption(
        'omit-tag',
        'omit_tag',
        str,
        'Tag marking cells to omit entirely',
        build=_omit_action,
    ),
    ScrubberOption(
        'note-tag',
        'note_tag',
        str,
        'Option name marking cells to save to notes',
        takes_text=True,
        build=_note_action,
    ),
    ScrubberOption(
        'clear-tag',
        'clear_tag',
        str,
        'Tag marking cells to clear',
        takes_text=True,
        build=_clear_action,
    ),
    ScrubberOption(
        'clear-text',
        'clear_text',
        str,
        'Text for cleared cells where unspecified',
    ),
    ScrubberOption(
        'clear-text-markdown',
        'clear_text_markdown',
        str,
        'Text for cleared markdown cells where unspecified',
    ),
)


def _without_results(cell: Cell) -> Cell:
    """A copy of ``cell`` carrying none of the results of having been run.

    A code cell's ``outputs`` and ``execution_count`` are *required* by the
    nbformat schema, so they are emptied rather than removed; any other cell
    type must not carry them at all, so there they are dropped.
    """
    updated: Cell = {**cell}

    if updated.get('cell_type') == 'code':
        updated['outputs'] = []
        updated['execution_count'] = None
    else:
        updated.pop('outputs', None)
        updated.pop('execution_count', None)

    return updated


def _without_scrubber_tags(cell: Cell, names: frozenset[str]) -> Cell:
    """A copy of ``cell`` carrying none of the metadata tags ``names`` holds.

    Only this tool's names go, and the shared key goes only when nothing else is
    left -- an empty list would mark the cell just as the tag did.
    """
    metadata = cell.get('metadata', {})
    tags = metadata.get('tags', [])

    kept = [tag for tag in tags if tag not in names]
    if len(kept) == len(tags):
        return cell

    updated = {**metadata, 'tags': kept}
    if not kept:
        del updated['tags']

    return {**cell, 'metadata': updated}


@dataclass(frozen=True)
class Scrubber:
    """One run's options, resolved once into everything reading a cell needs.

    The spellings a run configures cannot change while it lasts, so the tuple of
    parser options, the precedence order, and the tag names to strip are all
    derived up front rather than rebuilt for every cell.
    """

    opts: ScrubbingOptions
    #: What :func:`parse_cell_options` is handed.
    options: tuple[Option, ...]
    #: Each cell-marking option under this run's spelling, with what that option
    #: builds, in the precedence order :data:`OPTIONS` states.
    markers: tuple[tuple[str, _Build], ...]
    #: The names this tool takes back out of ``metadata.tags``.
    names: frozenset[str]

    @classmethod
    def for_options(cls, opts: ScrubbingOptions) -> Self:
        """The scrubber a run configured by ``opts`` reads its cells with."""
        marking = tuple(
            (getattr(opts, option.field), option.takes_text, option.build)
            for option in OPTIONS
            if option.build is not None
        )
        return cls(
            opts=opts,
            options=tuple(Option(name, takes_text) for name, takes_text, _ in marking),
            markers=tuple((name, build) for name, _, build in marking),
            names=frozenset(name for name, _, _ in marking),
        )

    def default_clear_text(self, cell_type: str) -> str:
        """The replacement text for a cleared cell whose author supplied none.

        A placeholder has to read as the kind of cell it lands in: the code
        default is a comment, which markdown would render as a heading.
        """
        if cell_type == 'markdown':
            return self.opts.clear_text_markdown
        return self.opts.clear_text

    def decide(self, cell: Cell) -> CellAction:
        """Decide what happens to a cell.

        A tag carries presence and nothing else, exactly like a valueless header
        option, so both spellings merge into one mapping, the header winning.

        Raises:
            ScrubberError: If the options are malformed, misplaced, or ambiguous.
        """
        tags: list[str] = cell.get('metadata', {}).get('tags', [])
        cell_type = cell.get('cell_type', '')
        source = get_cell_source(cell)
        header = parse_cell_options(cell_type, source, self.options)

        _check_one_scrubber_option(header, self.names)

        cell_options: dict[str, Any] = {**dict.fromkeys(tags), **header.options}
        marked = _Marked(self, cell_type, frozenset(tags), header)

        for name, build in self.markers:
            if name in cell_options:
                return build(cell_options[name], marked)

        return Keep()

    def apply(self, cell: Cell, action: CellRewrite) -> Cell:
        """Return a new cell with ``action`` applied; ``cell`` is left alone.

        ``Omit`` is not accepted: an omitted cell has no output form.
        """
        updated = _without_results(_without_scrubber_tags(cell, self.names))

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
