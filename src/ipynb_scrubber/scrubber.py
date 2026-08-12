"""Read one run's options off a cell, and rewrite the cell accordingly."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import assert_never

from .actions import CellAction, CellRewrite, Clear, Keep, Note
from .exceptions import ProcessingError
from .header import Header, HeaderOption, parse_cell_options
from .notebook import Cell, evolve, get_cell_source, to_cell_source
from .options import MARKERS, ScrubbingOptions, _Build, _Marked


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
class _Marker(HeaderOption):
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

        In the precedence order :data:`~.options.MARKERS` states, and shaped as
        the header parser wants its options, so this is also what it is handed.
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
