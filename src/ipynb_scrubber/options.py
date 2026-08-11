from __future__ import annotations

import contextlib
import re

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

#: What an option name may look like: nothing YAML would quote as a bare key.
TAG_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]*')

#: What YAML tags a scalar it reads as text. Asked of YAML's own resolver, not
#: a word list kept here, so the answer is the one PyYAML gives on a header.
_STRING_TAG = 'tag:yaml.org,2002:str'

#: One resolver for the whole module: it carries no per-document state, and a
#: name is checked on every options instance a config override derives.
_resolve = yaml.resolver.Resolver().resolve


def is_plain_name(name: str) -> bool:
    """Whether ``name`` is spelled the way an option header key must be."""
    return TAG_NAME.fullmatch(name) is not None


def reads_back_as_text(name: str) -> bool:
    """Whether YAML reads ``name`` off an option header as this same text.

    The alternative is YAML resolving it to a bool or None.
    """
    return _resolve(yaml.ScalarNode, name, (True, False)) == _STRING_TAG


@dataclass(frozen=True)
class Option:
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
    #: The options written as a block scalar.
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
    #: The original source line behind each line of ``header``. Empty for a
    #: header that is replaced whole rather than a line at a time.
    kept_lines: tuple[str, ...] = ()


def _code_header(source: str) -> _Split:
    """Split a code cell's source at the end of its leading ``#|`` run.

    Markers lose at most one following space; a blank line joins only if ``#|``
    follows.
    """
    lines = source.split('\n')
    # Each header line paired with the source line it came from.
    header: list[tuple[str, str]] = []
    pending: list[tuple[str, str]] = []
    end = 0

    for index, line in enumerate(lines):
        text = line.lstrip()
        if text.startswith(CODE_MARKER):
            header.extend(pending)
            pending.clear()
            header.append((text[len(CODE_MARKER) :].removeprefix(' '), line))
            end = index + 1
        elif text:
            break
        else:
            pending.append(('', line))

    return _Split(
        header='\n'.join(yaml_line for yaml_line, _ in header),
        body='\n'.join(lines[end:]),
        kept_lines=tuple(source_line for _, source_line in header),
    )


def _markdown_header(source: str) -> _Split:
    """Split a markdown cell's source at the end of its leading HTML comments.

    No kept lines are reported, so the header is replaced whole: the delimiters
    do not survive their contents being removed.

    Raises:
        ProcessingError: If a comment is never closed.
    """
    lines = source.split('\n')
    header: list[str] = []
    pending: list[str] = []
    index = 0
    end = 0

    while index < len(lines):
        text = lines[index].strip()
        if not text:
            pending.append('')
            index += 1
            continue
        if not text.startswith(MARKDOWN_MARKER):
            break

        header.extend(pending)
        pending.clear()
        inner = text[len(MARKDOWN_MARKER) :].rstrip()
        index += 1

        if inner.endswith(MARKDOWN_SUFFIX):
            header.append(
                inner.removesuffix(MARKDOWN_SUFFIX).rstrip().removeprefix(' '),
            )
            end = index
            continue

        header.append(inner.removeprefix(' '))
        while True:
            if index >= len(lines):
                raise ProcessingError(
                    'Unterminated comment in cell option header: '
                    f"expected a line containing only '{MARKDOWN_SUFFIX}'",
                )
            if lines[index].strip() == MARKDOWN_SUFFIX:
                index += 1
                break
            header.append(lines[index])
            index += 1
        end = index

    return _Split('\n'.join(header), '\n'.join(lines[end:]))


_HEADERS: dict[str, Callable[[str], _Split]] = {
    'code': _code_header,
    'markdown': _markdown_header,
}


#: What YAML says when a plain value carries a second ``:``, much the likeliest
#: way a header stops being YAML (a caption reading ``Figure 1: a plot``).
_UNQUOTED_COLON = 'mapping values are not allowed here'


def _describe(error: yaml.YAMLError, text: str) -> str:
    """Turn a YAML parse failure into advice aimed at the header's author.

    Only a ``MarkedYAMLError`` carries a line or a problem, and may carry
    neither.
    """
    if isinstance(error, yaml.MarkedYAMLError):
        mark = error.problem_mark
        lines = text.split('\n')

        if mark is not None and 0 <= mark.line < len(lines):
            if '\t' in lines[mark.line]:
                return (
                    f'Invalid cell option header: line {mark.line + 1} contains '
                    'a tab. The header is YAML, which forbids tabs as '
                    'whitespace; indent it with spaces'
                )
            problem = error.problem
            if problem == _UNQUOTED_COLON:
                return (
                    f'Invalid cell option header: line {mark.line + 1} has a '
                    "second ':' in its value. The header is YAML, so a value "
                    "containing ':' or '#' has to be quoted "
                    '(name: "Figure 1: a plot")'
                )
            if problem:
                return f'Invalid cell option header: {problem} (line {mark.line + 1})'

    return f'Invalid cell option header: {error}'


def _reject_repeated_names(
    entries: Collection[tuple[yaml.Node, yaml.Node]],
    prefix: str = '',
) -> None:
    """Refuse a name the header carries twice, since YAML keeps only the last.

    Raises:
        ProcessingError: If a name appears more than once at any level.
    """
    seen: set[tuple[str, str]] = set()
    for key, value in entries:
        if not isinstance(key, yaml.ScalarNode):
            continue
        # The tag is part of the identity: quoted '12' and bare 12 are the
        # same characters but different names.
        identity = (key.tag, key.value)
        if identity in seen:
            raise ProcessingError(
                f"Duplicate option '{prefix}{key.value}' in cell option header",
            )
        seen.add(identity)
        if isinstance(value, yaml.MappingNode):
            _reject_repeated_names(value.value, f'{prefix}{key.value}.')


def _reject_commented_value(name: str, value: yaml.Node, lines: list[str]) -> None:
    """Refuse a plain scalar that YAML cut short at a ``#``.

    Raises:
        ProcessingError: If the value is followed by a comment.
    """
    if not isinstance(value, yaml.ScalarNode) or value.style is not None:
        return

    end = value.end_mark
    if end.line >= len(lines):
        return
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
    entries: Collection[tuple[yaml.ScalarNode, yaml.Node]],
    text: str,
    names: Collection[str],
) -> None:
    """Refuse an option whose value YAML cut short at a ``#``.

    An unquoted ``#`` opens a comment and the rest of the line goes with it.
    Replacement text is full of Python comments, so the loss is likely and the
    result plausible enough to ship unnoticed: the option keeps whatever came
    before the ``#``, or falls back to its default.

    Raises:
        ProcessingError: If an option's value is followed by a comment.
    """
    lines = text.split('\n')

    for key, value in entries:
        if key.value not in names:
            continue
        if isinstance(value, yaml.MappingNode):
            for entry, entry_value in value.value:
                if isinstance(entry, yaml.ScalarNode):
                    _reject_commented_value(
                        f'{key.value}.{entry.value}',
                        entry_value,
                        lines,
                    )
            continue
        _reject_commented_value(key.value, value, lines)


def _block_styled(node: yaml.MappingNode) -> frozenset[str]:
    """The names of the options written as a block scalar."""
    return frozenset(
        key.value
        for key, value in node.value
        if isinstance(key, yaml.ScalarNode)
        and isinstance(value, yaml.ScalarNode)
        and value.style in _BLOCK_STYLES
    )


def _kept_header(
    node: yaml.MappingNode,
    split: _Split,
    names: Collection[str],
) -> str:
    """The header's own source lines, minus those this tool's options occupy.

    An option owns every line from its key to the next, which keeps a block
    scalar's content with the option that opened it.
    """
    if not split.kept_lines:
        return ''

    total = len(split.kept_lines)
    keys = [
        (key.value, key.start_mark.line)
        for key, _ in node.value
        if isinstance(key, yaml.ScalarNode)
    ]

    dropped: set[int] = set()
    for index, (name, start) in enumerate(keys):
        if name not in names:
            continue
        end = keys[index + 1][1] if index + 1 < len(keys) else total
        dropped.update(range(max(start, 0), min(end, total)))

    return '\n'.join(
        line for index, line in enumerate(split.kept_lines) if index not in dropped
    )


def _claims_a_name(node: yaml.Node, lines: list[str], names: Collection[str]) -> bool:
    """Whether a header holding no mapping still writes one of ``names``.

    Only asked of a header the author already got wrong, so the reading leans
    toward over-claiming: a missed claim leaves the cell unscrubbed, which for
    ``scrub-omit`` means shipping the solution. A name counts wherever written
    -- key, list item, or the line a plain scalar opens on.
    """
    if isinstance(node, yaml.MappingNode):
        return any(_claims_a_name(key, lines, names) for key, _ in node.value)
    if isinstance(node, yaml.SequenceNode):
        return any(_claims_a_name(item, lines, names) for item in node.value)
    if not isinstance(node, yaml.ScalarNode):
        return False
    return node.value in names or _opening_line(node, lines) in names


def _opening_line(node: yaml.Node, lines: list[str]) -> str:
    """The header line on which ``node`` begins, stripped."""
    index = node.start_mark.line
    return lines[index].strip() if 0 <= index < len(lines) else ''


@contextlib.contextmanager
def _loader(text: str) -> Iterator[yaml.SafeLoader]:
    """A YAML loader for ``text``, disposed of once the caller is done.

    Construction is part of reading, so a malformed header can fail here.
    """
    loader = yaml.SafeLoader(text)
    try:
        yield loader
    finally:
        loader.dispose()


def _read(split: _Split, options: Collection[Option]) -> Header:
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

        data = loader.construct_document(node)

        if not isinstance(node, yaml.MappingNode):
            lines = split.header.split('\n')
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

        ours = [
            (key, value)
            for key, value in node.value
            if isinstance(key, yaml.ScalarNode) and key.value in names
        ]

        _reject_repeated_names(ours)
        _reject_commented_values(
            ours,
            split.header,
            frozenset(option.name for option in options if option.takes_text),
        )

        return Header(
            data,
            _block_styled(node),
            kept=_kept_header(node, split, names),
        )


def parse_cell_options(
    cell_type: str,
    source: str,
    options: Collection[Option],
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

    split = build(source)
    if not split.header.strip():
        return Header(body=split.body)

    try:
        header = _read(split, options)
    except yaml.YAMLError as e:
        # No graph, so no way to say whose header it is. Guessing from raw text
        # claims headers that merely look like ours; staying quiet ships a cell
        # this tool was told to scrub. Report it.
        raise ProcessingError(_describe(e, split.header)) from e

    # Where the body starts is a property of the source, not of the header.
    return replace(header, body=split.body)
