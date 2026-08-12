from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cached_property
from typing import Any, Self, assert_never

from .exceptions import ProcessingError, ScrubberError
from .notebook import Cell, evolve, get_cell_source, to_cell_source
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
    clear_text_raw: str = 'TODO: Implement this'
    omit_tag: str = 'scrub-omit'
    note_reference: str = '# (See notes: {id})'
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
            reject_wrong_type(option.key, getattr(self, option.field), str)

        named = {option.key: getattr(self, option.field) for option in MARKERS}

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


#: Which option holds the replacement text a cleared cell of each type gets,
#: since no one spelling suits them all: the code text is a comment, which
#: markdown renders as a heading and a raw cell emits verbatim as itself. One
#: entry per :data:`~.notebook.CELL_TYPES` member, which is every cell type that
#: survives validation, so the lookup below needs no default.
_CLEAR_TEXT_FIELDS: dict[str, str] = {
    'code': 'clear_text',
    'markdown': 'clear_text_markdown',
    'raw': 'clear_text_raw',
}


@dataclass(frozen=True)
class _Marked:
    """A cell an option was found on, as the builders below need to see it."""

    opts: ScrubbingOptions
    cell_type: str
    #: The cell's metadata tags, whole and unfiltered. Not a record of where
    #: this cell's option came from -- the caller asks each source directly and
    #: does not report back. It is here for the one builder that has to refuse a
    #: name written as a tag *anywhere* on the cell, whichever spelling brought
    #: it here, so reading it as provenance would say something it does not.
    tags: frozenset[str]
    header: Header

    @property
    def default_clear_text(self) -> str:
        """The replacement text for a cleared cell whose author supplied none.

        :data:`_CLEAR_TEXT_FIELDS` picks it by cell type. A cell type it does
        not name never reaches here -- validation refuses the notebook first --
        so a ``KeyError`` would be this tool disagreeing with itself.
        """
        field = _CLEAR_TEXT_FIELDS[self.cell_type]
        text: str = getattr(self.opts, field)
        return text


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
        ProcessingError: On the name appearing as a metadata tag (nowhere to
            put the id), a non-code cell, an unusable id, or non-string text.
        ScrubberError: On an undefined key.
    """
    opts = marked.opts

    # The name being tagged at all is refused, not merely the option having
    # arrived that way: a tag alongside a well-formed header option is a
    # spelling of this option that cannot work, so it is worth saying so.
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
            f"Option '{marked.opts.omit_tag}' takes no value, but got {value!r}",
        )
    return Omit()


def _clear_action(value: Any, marked: _Marked) -> Clear:
    """Build the Clear a ``scrub-clear`` option describes.

    Raises:
        ProcessingError: If the value is present but is not text.
    """
    return Clear(
        _replacement_text(
            marked.opts.clear_tag,
            value,
            marked.default_clear_text,
        ),
        marked.header.kept,
    )


@dataclass(frozen=True)
class ScrubberOption:
    """One option this tool defines: how it is spelled, and what holds it.

    That is, the TOML key and CLI flag a run configures it by, and which
    :class:`ScrubbingOptions` field carries the value.
    """

    #: TOML key, and the CLI flag spelled ``--<key>``.
    key: str
    field: str
    help: str


@dataclass(frozen=True)
class MarkerOption(ScrubberOption):
    """An option whose value is a name cells are marked with.

    Its ``build`` says what a cell carrying that name becomes, and
    ``takes_text`` whether the name may be written with replacement text after
    it.
    """

    build: _Build
    takes_text: bool = False


#: Every option this tool defines, whatever it does: this is what the CLI and a
#: config file offer, so an option missing here cannot be configured at all.
OPTIONS: tuple[ScrubberOption, ...] = (
    MarkerOption(
        'omit-tag',
        'omit_tag',
        'Tag marking cells to omit entirely',
        build=_omit_action,
    ),
    MarkerOption(
        'note-tag',
        'note_tag',
        'Option name marking cells to save to notes',
        build=_note_action,
        takes_text=True,
    ),
    ScrubberOption(
        'note-reference',
        'note_reference',
        'Marker pointing a noted cell at its note, with {id} for the note id',
    ),
    MarkerOption(
        'clear-tag',
        'clear_tag',
        'Tag marking cells to clear',
        build=_clear_action,
        takes_text=True,
    ),
    ScrubberOption(
        'clear-text',
        'clear_text',
        'Text for cleared cells where unspecified',
    ),
    ScrubberOption(
        'clear-text-markdown',
        'clear_text_markdown',
        'Text for cleared markdown cells where unspecified',
    ),
    ScrubberOption(
        'clear-text-raw',
        'clear_text_raw',
        'Text for cleared raw cells where unspecified',
    ),
)

#: The options that mark cells, in the order a cell's own options are considered
#: in: omit first because dropping a cell subsumes every rewrite of it, and note
#: before clear because a note is a clear that also files away what it removed.
MARKERS: tuple[MarkerOption, ...] = tuple(
    option for option in OPTIONS if isinstance(option, MarkerOption)
)


def _without_results(cell: Cell) -> Cell:
    """A copy of ``cell`` carrying none of the results of having been run.

    A code cell's ``outputs`` and ``execution_count`` are *required* by the
    nbformat schema, so they are emptied rather than removed; any other cell
    type must not carry them at all, so there they are dropped.
    """
    updated: Cell = evolve(cell)

    if updated['cell_type'] == 'code':
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

    # metadata's target is a plain dict[str, Any], not a TypedDict, so an
    # annotated changes mapping here would check nothing; it stays a keyword
    # argument. The cell's own new metadata is written by subscript, where mypy
    # does check a TypedDict's key and value types; evolve's **changes: Any
    # would otherwise wave a misspelled key or a wrong value through unchecked.
    tagless = evolve(metadata, tags=kept)
    if not kept:
        del tagless['tags']

    updated: Cell = evolve(cell)
    updated['metadata'] = tagless
    return updated


@dataclass(frozen=True)
class _Marker(Option):
    """A marking option under one run's spelling, with what it builds."""

    build: _Build


@dataclass(frozen=True)
class Scrubber:
    """One run's options, resolved once into everything reading a cell needs.

    The spellings a run configures cannot change while it lasts, so the markers
    and the tag names to strip are derived from ``opts`` once and cached, rather
    than rebuilt for every cell.
    """

    opts: ScrubbingOptions

    @cached_property
    def markers(self) -> tuple[_Marker, ...]:
        """Each marking option under this run's spelling.

        In the precedence order :data:`MARKERS` states, and shaped as the header
        parser wants its options, so this is also what it is handed.
        """
        return tuple(
            _Marker(getattr(self.opts, option.field), option.takes_text, option.build)
            for option in MARKERS
        )

    @cached_property
    def names(self) -> frozenset[str]:
        """The names this tool takes back out of ``metadata.tags``."""
        return frozenset(marker.name for marker in self.markers)

    def decide(self, cell: Cell) -> CellAction:
        """Decide what happens to a cell.

        Each marker asks the two places a cell can carry it, header first, so
        the header wins a name written both ways. A tag carries presence and
        nothing else, which is the value a valueless header option resolves to,
        so a tag builds from ``None``.

        Raises:
            ScrubberError: If the options are malformed, misplaced, or ambiguous.
        """
        tags: list[str] = cell.get('metadata', {}).get('tags', [])
        cell_type = cell['cell_type']
        source = get_cell_source(cell)
        header = parse_cell_options(cell_type, source, self.markers)

        _check_one_scrubber_option(header, self.names)

        tag_set = frozenset(tags)
        marked = _Marked(self.opts, cell_type, tag_set, header)

        for marker in self.markers:
            if marker.name in header.options:
                return marker.build(header.options[marker.name], marked)
            if marker.name in tag_set:
                return marker.build(None, marked)

        return Keep()

    def apply(self, cell: Cell, action: CellRewrite) -> Cell:
        """Return a new cell with ``action`` applied; ``cell`` is left alone.

        ``Omit`` is not accepted: an omitted cell has no output form.

        A note's reference marker is ``note-reference`` with ``{id}``, its only
        placeholder, replaced by the note id; every other brace is left as
        written.
        """
        # Both helpers rebuild the cell in its own class; neither may go back
        # to a dict literal, or the class is lost for the cells that need it.
        updated = _without_results(_without_scrubber_tags(cell, self.names))

        match action:
            case Keep():
                return updated
            case Clear(text=text, header=kept):
                source = _under_header(kept, text)
            case Note(note_id=note_id, text=text, header=kept):
                suffix = f'\n{text}' if text else ''
                reference = self.opts.note_reference.replace('{id}', note_id)
                source = _under_header(kept, f'{reference}{suffix}')
            case _:
                assert_never(action)

        updated['source'] = to_cell_source(cell, source)
        return updated
