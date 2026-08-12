"""Every option this tool defines, and what a cell carrying one becomes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Self

from .actions import CellAction, Clear, Note, Omit
from .exceptions import ProcessingError, ScrubberError
from .header import Header
from .validation import (
    is_plain_name,
    reads_back_as_text,
    reject_unknown_keys,
    reject_wrong_type,
)


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
