"""Read a cell's YAML option header and say what it holds."""

from __future__ import annotations

import contextlib

from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, field, replace
from typing import Any

import yaml

from .exceptions import ProcessingError

CODE_MARKER = '#|'
MARKDOWN_MARKER = '<!--'
MARKDOWN_SUFFIX = '-->'

#: The scalar styles that open a block: content lives on the lines below.
_BLOCK_STYLES = frozenset({'|', '>'})


@dataclass(frozen=True)
class HeaderOption:
    """An option this tool defines, as the header parser needs to know it.

    ``takes_text`` marks the options whose value a YAML comment can eat.
    """

    name: str
    takes_text: bool


@dataclass(frozen=True)
class Header:
    """What a cell's option header carries.

    That is the mapping it holds with values resolved by YAML, and the source
    below it, i.e. the cell's real content.
    """

    options: dict[str, Any] = field(default_factory=dict)
    #: Which of this tool's own options are written as a block scalar. A
    #: neighbour's block style is the neighbour's business, so it is not here.
    block_styled: frozenset[str] = frozenset()
    body: str = ''
    #: Header source lines belonging to somebody else's options, which are part
    #: of the cell and go above whatever replaces it.
    kept: str = ''


@dataclass(frozen=True)
class _Split:
    """A cell's source divided at the end of its option header."""

    #: The YAML text the header carries, with its comment syntax stripped.
    header: str
    #: The source below the header, verbatim.
    body: str
    #: Which source line each line of ``header`` was read off, so a line number
    #: YAML reports about the header can be reported about the cell instead.
    #: One entry per header line, always.
    source_lines: tuple[int, ...] = ()
    #: The original source line behind each line of ``header``. Empty for a
    #: header that is replaced whole rather than a line at a time.
    kept_lines: tuple[str, ...] = ()


def _code_header(source: str) -> _Split:
    """Split a code cell's source at the end of its leading ``#|`` run.

    Markers lose at most one following space; a blank line joins only if ``#|``
    follows.
    """
    lines = source.split('\n')
    # Each header line paired with the source line it came from. Every line
    # above the last marker is here, blanks included, so the pairing is the
    # identity -- which is what lets a code cell keep its header line by line.
    header: list[tuple[str, int]] = []
    pending: list[tuple[str, int]] = []
    end = 0

    for index, line in enumerate(lines):
        text = line.lstrip()
        if text.startswith(CODE_MARKER):
            header.extend(pending)
            pending.clear()
            header.append((text[len(CODE_MARKER) :].removeprefix(' '), index))
            end = index + 1
        elif text:
            break
        else:
            pending.append(('', index))

    return _Split(
        header='\n'.join(yaml_line for yaml_line, _ in header),
        body='\n'.join(lines[end:]),
        source_lines=tuple(origin for _, origin in header),
        kept_lines=tuple(lines[origin] for _, origin in header),
    )


def _markdown_header(source: str) -> _Split:
    """Split a markdown cell's source at the end of its leading HTML comments.

    No kept lines are reported, so the header is replaced whole: the delimiters
    do not survive their contents being removed. Which source line each header
    line came from is still reported, since a closing ``-->`` is a source line
    of its own and leaves the two out of step from there on.

    Raises:
        ProcessingError: If a comment is never closed.
    """
    lines = source.split('\n')
    # Each header line paired with the source line it came from, as in
    # _code_header -- except that here the pairing is not the identity.
    header: list[tuple[str, int]] = []
    pending: list[tuple[str, int]] = []
    index = 0
    end = 0

    while index < len(lines):
        text = lines[index].strip()
        if not text:
            pending.append(('', index))
            index += 1
            continue
        if not text.startswith(MARKDOWN_MARKER):
            break

        header.extend(pending)
        pending.clear()
        opener = index
        inner = text[len(MARKDOWN_MARKER) :].rstrip()
        index += 1

        if inner.endswith(MARKDOWN_SUFFIX):
            closed = inner.removesuffix(MARKDOWN_SUFFIX).rstrip().removeprefix(' ')
            header.append((closed, opener))
            end = index
            continue

        header.append((inner.removeprefix(' '), opener))
        while True:
            if index >= len(lines):
                raise ProcessingError(
                    'Unterminated comment in cell option header: '
                    f"expected a line containing only '{MARKDOWN_SUFFIX}'",
                )
            if lines[index].strip() == MARKDOWN_SUFFIX:
                index += 1
                break
            header.append((lines[index], index))
            index += 1
        end = index

    return _Split(
        header='\n'.join(yaml_line for yaml_line, _ in header),
        body='\n'.join(lines[end:]),
        source_lines=tuple(origin for _, origin in header),
    )


_HEADERS: dict[str, Callable[[str], _Split]] = {
    'code': _code_header,
    'markdown': _markdown_header,
}


#: What YAML says when a plain value carries a second ``:``, much the likeliest
#: way a header stops being YAML (a caption reading ``Figure 1: a plot``).
_UNQUOTED_COLON = 'mapping values are not allowed here'


def _describe(error: yaml.YAMLError, split: _Split) -> str:
    """Turn a YAML parse failure into advice aimed at the header's author.

    A mark places the problem in the header text YAML was handed, but the
    author reads their own cell, so the text is looked at where YAML found it
    and the line is numbered where the author wrote it.

    Only a ``MarkedYAMLError`` carries a line or a problem, and may carry
    neither.
    """
    if isinstance(error, yaml.MarkedYAMLError):
        mark = error.problem_mark
        lines = split.header.split('\n')

        if mark is not None and 0 <= mark.line < len(lines):
            number = split.source_lines[mark.line] + 1
            if '\t' in lines[mark.line]:
                return (
                    f'Invalid cell option header: line {number} contains '
                    'a tab. The header is YAML, which forbids tabs as '
                    'whitespace; indent it with spaces'
                )
            problem = error.problem
            if problem == _UNQUOTED_COLON:
                return (
                    f'Invalid cell option header: line {number} has a '
                    "second ':' in its value. The header is YAML, so a value "
                    "containing ':' or '#' has to be quoted "
                    '(name: "Figure 1: a plot")'
                )
            if problem:
                return f'Invalid cell option header: {problem} (line {number})'

    return f'Invalid cell option header: {error}'


# Everything below reads the header's geometry off PyYAML's marks, and every
# mark points into the very text PyYAML was handed: a node starts on a line of
# the header, and a plain scalar ends on one. So a line number taken from a
# mark indexes the header's lines directly, with nothing to bounds-check.


@dataclass(frozen=True)
class _Entry:
    """One entry of a header's mapping: a name, its value, and its own lines.

    ``span`` is every header line from the entry's key down to the next key's,
    which keeps a block scalar's content with the option that opened it.
    """

    name: str
    key: yaml.ScalarNode
    value: yaml.Node
    span: range

    @property
    def block_styled(self) -> bool:
        """Whether the value is written as a block scalar."""
        return (
            isinstance(self.value, yaml.ScalarNode)
            and self.value.style in _BLOCK_STYLES
        )

    @property
    def children(self) -> tuple[_Entry, ...]:
        """The entries of a mapping value; nothing else has any."""
        if not isinstance(self.value, yaml.MappingNode):
            return ()
        return _entries(self.value, self.span.stop)


def _entries(node: yaml.MappingNode, end: int) -> tuple[_Entry, ...]:
    """The mapping's entries, over a header whose lines run out at ``end``.

    Only a scalar key names an entry, so a key of any other shape leaves its
    lines to the entry above it.
    """
    pairs = [
        (key, value) for key, value in node.value if isinstance(key, yaml.ScalarNode)
    ]
    # One boundary per entry, plus the end: entry i owns up to boundary i + 1.
    bounds = [key.start_mark.line for key, _ in pairs] + [end]
    return tuple(
        _Entry(key.value, key, value, range(bounds[index], bounds[index + 1]))
        for index, (key, value) in enumerate(pairs)
    )


def _reject_repeated_names(entries: Collection[_Entry], prefix: str = '') -> None:
    """Refuse a name the header carries twice, since YAML keeps only the last.

    Raises:
        ProcessingError: If a name appears more than once at any level.
    """
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        # The tag is part of the identity: quoted '12' and bare 12 are the
        # same characters but different names.
        identity = (entry.key.tag, entry.name)
        if identity in seen:
            raise ProcessingError(
                f"Duplicate option '{prefix}{entry.name}' in cell option header",
            )
        seen.add(identity)
        _reject_repeated_names(entry.children, f'{prefix}{entry.name}.')


def _reject_commented_value(name: str, value: yaml.Node, lines: list[str]) -> None:
    """Refuse a plain scalar that YAML cut short at a ``#``.

    Raises:
        ProcessingError: If the value is followed by a comment.
    """
    if not isinstance(value, yaml.ScalarNode) or value.style is not None:
        return

    end = value.end_mark
    if not lines[end.line][end.column :].lstrip().startswith('#'):
        return

    raise ProcessingError(
        f"Option '{name}' is cut short by a YAML comment: in the option "
        "header an unquoted '#' starts a comment, so the text from there to "
        'the end of the line is discarded. Quote the value '
        f'({name}: "# TODO: your code here") or write it as a block scalar '
        f"('{name}: |' with the text indented on the lines below)",
    )


def _reject_commented_values(
    entries: Collection[_Entry],
    lines: list[str],
    names: Collection[str],
) -> None:
    """Refuse an option whose value YAML cut short at a ``#``.

    An unquoted ``#`` opens a comment and the rest of the line goes with it.
    Replacement text is full of Python comments, so the loss is likely and the
    result plausible enough to ship unnoticed: the option keeps whatever came
    before the ``#``, or falls back to its default.

    Only the entries directly under an option's name are checked: further down
    is the shape of somebody's data, not a value a comment can quietly halve.

    Raises:
        ProcessingError: If an option's value is followed by a comment.
    """
    for entry in entries:
        if entry.name not in names:
            continue
        if isinstance(entry.value, yaml.MappingNode):
            for child in entry.children:
                _reject_commented_value(
                    f'{entry.name}.{child.name}',
                    child.value,
                    lines,
                )
            continue
        _reject_commented_value(entry.name, entry.value, lines)


def _claims_a_name(node: yaml.Node, lines: list[str], names: Collection[str]) -> bool:
    """Whether a header holding no mapping still writes one of ``names``.

    Only asked of a header the author already got wrong, so the reading leans
    toward over-claiming: a missed claim leaves the cell unscrubbed, which for
    ``scrub-omit`` means shipping the solution. A name counts wherever written
    -- key, list item, or the line a plain scalar opens on.

    A node is a mapping, a sequence, or a scalar, so what reaches the last line
    is a scalar.
    """
    if isinstance(node, yaml.MappingNode):
        return any(_claims_a_name(key, lines, names) for key, _ in node.value)
    if isinstance(node, yaml.SequenceNode):
        return any(_claims_a_name(item, lines, names) for item in node.value)
    return node.value in names or _opening_line(node, lines) in names


def _opening_line(node: yaml.Node, lines: list[str]) -> str:
    """The header line on which ``node`` begins, stripped."""
    return lines[node.start_mark.line].strip()


@contextlib.contextmanager
def _loader(text: str) -> Iterator[yaml.SafeLoader]:
    """A YAML loader for ``text``, disposed of once the caller is done.

    Construction is part of reading, so a malformed header can fail here.
    """
    loader = yaml.SafeLoader(text)
    try:
        yield loader
    finally:
        # PyYAML's stubs leave dispose untyped; the ignore goes when they don't.
        loader.dispose()  # type: ignore[no-untyped-call]


def _read(split: _Split, options: Collection[HeaderOption]) -> Header:
    """The Header the split's header text describes, from a single parse.

    One loader yields both the node graph and the values, the graph carrying
    what resolved values drop: block styles, and where each value stopped.

    Raises:
        yaml.YAMLError: If the header is not well-formed YAML.
        ProcessingError: If it names one of this tool's options wrongly.
    """
    names = {option.name for option in options}

    with _loader(split.header) as loader:
        node = loader.get_single_node()
        if node is None:
            return Header()

        # Untyped in PyYAML's stubs, as dispose is above.
        data = loader.construct_document(node)  # type: ignore[no-untyped-call]
        lines = split.header.split('\n')

        if not isinstance(node, yaml.MappingNode):
            if not _claims_a_name(node, lines, names):
                return Header()
            # A bare option name is told about its missing colon; the second
            # message is for shapes no option can be read out of at all.
            opener = _opening_line(node, lines)
            if opener in names:
                raise ProcessingError(
                    f"Option '{opener}' is missing its colon. The cell option "
                    "header is YAML and an option is a 'name: value' entry, so "
                    f"write '{opener}:'",
                )
            raise ProcessingError(
                "Cell option header must be a mapping of 'name: value' "
                f'entries, but got {type(data).__name__}',
            )

        ours = [entry for entry in _entries(node, len(lines)) if entry.name in names]

        _reject_repeated_names(ours)
        _reject_commented_values(
            ours,
            lines,
            frozenset(option.name for option in options if option.takes_text),
        )

        # A code cell's kept lines stand one to one with the header's own, so
        # an entry's span indexes both. A markdown cell keeps none of them.
        dropped = {index for entry in ours for index in entry.span}
        return Header(
            data,
            frozenset(entry.name for entry in ours if entry.block_styled),
            kept='\n'.join(
                line
                for index, line in enumerate(split.kept_lines)
                if index not in dropped
            ),
        )


def _names_an_option(source: str, options: Collection[HeaderOption]) -> bool:
    """Whether ``source`` writes one of this tool's option names anywhere in it.

    Only ever asked before deciding to *attempt* a parse, never to settle who
    owns what: ownership is read off the parsed keys, below. So the reading is
    deliberately loose, and it can only err toward parsing a header this tool
    does not own -- which is what it would have done regardless. It cannot err
    the other way: a name is a literal string, and an option spelled anything
    other than that string does nothing at all.
    """
    return any(option.name in source for option in options)


def parse_cell_options(
    cell_type: str,
    source: str,
    options: Collection[HeaderOption],
) -> Header:
    """Parse the option header at the top of a cell's source.

    Code cells carry it as leading Quarto ``#|`` lines, markdown cells as
    leading HTML comments; either way the text is one YAML document, and other
    cell types yield an empty header.

    The header is shared, so ownership is settled off the parsed keys rather
    than the raw text -- that is what keeps a name inside a longer key, or in
    somebody else's value, from handing this tool a header it does not own. A
    non-mapping header has no keys to read ownership off, so there a name
    written anywhere counts: a colonless ``scrub-omit`` is reported rather than
    passed over, since passing it over ships the cell it meant to remove.

    Raises:
        ProcessingError: On malformed YAML, on a non-mapping header naming an
            option, or on an option repeated or eaten by a YAML comment.
    """
    build = _HEADERS.get(cell_type)
    if build is None:
        # No comment syntax to hide a header in, so the source is all body.
        return Header(body=source)

    if cell_type == 'markdown' and not _names_an_option(source, options):
        # An HTML comment is not a shared option header the way a '#|' run is
        # -- it is ordinary markdown, and a notebook is full of comments left
        # by formatters and site generators. Reading every one as YAML fails
        # the run over a '<!-- @format -->' this tool has no business parsing.
        return Header(body=source)

    split = build(source)
    if not split.header.strip():
        # An empty header is not YAML's to judge, and asking it anyway blames
        # the author for whitespace: a lone '#|' carrying a tab would come back
        # as an indentation to fix in a header that has no content at all.
        return Header(body=split.body)

    try:
        header = _read(split, options)
    except yaml.YAMLError as e:
        # No graph, so no way to say whose header it is. Guessing from raw text
        # claims headers that merely look like ours; staying quiet ships a cell
        # this tool was told to scrub. Report it.
        raise ProcessingError(_describe(e, split)) from e

    # Where the body starts is a property of the source, not of the header.
    return replace(header, body=split.body)
