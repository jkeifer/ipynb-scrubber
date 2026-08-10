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

#: The scalar styles that open a block: content lives on the lines below the
#: option, indented relative to it.
_BLOCK_STYLES = frozenset({'|', '>'})


@dataclass(frozen=True)
class Option:
    """An option this tool defines, as the header parser needs to know it.

    ``takes_text`` says whether the option's value is text the author wrote.
    That is the one thing the parser needs beyond the name: text can be eaten
    by a YAML comment and the loss is worth refusing, while an option that
    carries no value has nothing to lose and no advice about quoting to give.
    """

    name: str
    takes_text: bool


@dataclass(frozen=True)
class Header:
    """What a cell's option header carries.

    ``options`` is the mapping the header holds, with values resolved by YAML.
    ``block_styled`` names the options written as a block scalar, which tells a
    caller whether advice about block indentation is relevant. ``body`` is the
    cell's source below the header, which is the cell's actual content: the
    header is instructions about the cell, not part of it.
    """

    options: dict[str, Any] = field(default_factory=dict)
    block_styled: frozenset[str] = frozenset()
    body: str = ''
    #: The header's source lines that belong to somebody else's options, which
    #: are part of the cell and belong in the output above whatever replaces it.
    kept: str = ''


@dataclass(frozen=True)
class _Split:
    """A cell's source divided at the end of its option header."""

    #: The YAML text the header carries, with its comment syntax stripped.
    header: str
    #: The source below the header, verbatim.
    body: str
    #: The original source line behind each line of ``header``. Empty for a
    #: header that cannot be kept a line at a time, so it is replaced whole.
    kept_lines: tuple[str, ...] = ()


def _code_header(source: str) -> _Split:
    """Split a code cell's source at the end of its leading ``#|`` run.

    Each marker is stripped along with at most one following space, so that
    content indented relative to the marker keeps that indentation. A blank
    line participates in the header when another ``#|`` line follows it, which
    is what lets a block scalar contain one. A blank line with no ``#|`` after
    it belongs to the body.
    """
    lines = source.split('\n')
    # Each header line paired with the source line it was taken from, so the
    # two cannot fall out of step.
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

    A comment is either self-closing (``<!-- scrub-omit: -->``) or spans to a
    line containing only ``-->``. The inner text of each is concatenated into
    one document.

    No kept lines are reported, so the header is replaced whole rather than a
    line at a time. A comment's delimiters are not options and do not survive
    their contents being removed, and nothing but this tool writes options in a
    markdown cell's comments, so there is nothing there worth keeping.

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


#: What YAML says when a plain value carries a second ``:``. That is much the
#: likeliest way a header stops being YAML — a caption reading ``Figure 1: a
#: plot`` is the natural thing to write — and the parser's own words point at
#: the mechanism rather than the fix. Quarto, which reads the same header with
#: the same rules, gives the same advice: quote a value containing ``:``.
_UNQUOTED_COLON = 'mapping values are not allowed here'


def _describe(error: yaml.YAMLError, text: str) -> str:
    """Turn a YAML parse failure into advice aimed at the header's author."""
    mark = getattr(error, 'problem_mark', None)
    lines = text.split('\n')

    if mark is not None and 0 <= mark.line < len(lines):
        if '\t' in lines[mark.line]:
            return (
                f'Invalid cell option header: line {mark.line + 1} contains a '
                'tab. The header is YAML, which forbids tabs as whitespace; '
                'indent it with spaces'
            )
        problem = getattr(error, 'problem', None)
        if problem == _UNQUOTED_COLON:
            return (
                f'Invalid cell option header: line {mark.line + 1} has a second '
                "':' in its value. The header is YAML, so a value containing "
                "':' or '#' has to be quoted (name: \"Figure 1: a plot\")"
            )
        if problem:
            return f'Invalid cell option header: {problem} (line {mark.line + 1})'

    return f'Invalid cell option header: {error}'


def _missing_colon(name: str) -> ProcessingError:
    """The error for an option name written without the colon that names it.

    The header is YAML, and an option is a mapping entry, so the colon is what
    makes a name an option at all. Without it the name is a plain string, which
    also swallows any header lines below it.
    """
    return ProcessingError(
        f"Option '{name}' is missing its colon. The cell option header is YAML "
        f"and an option is a 'name: value' entry, so write '{name}:'",
    )


def _not_a_mapping(data: Any) -> ProcessingError:
    """The error for a header that holds something other than a mapping.

    A header whose opening line is a bare option name never reaches this: the
    colon it is missing is the more useful thing to say. What is left is a
    shape no option can be read out of at all.
    """
    return ProcessingError(
        "Cell option header must be a mapping of 'name: value' entries, "
        f'but got {type(data).__name__}',
    )


def _reject_repeated_names(node: yaml.MappingNode, prefix: str = '') -> None:
    """Refuse a name that the header carries more than once.

    YAML resolves a repeated name by keeping the last one. In an option header
    that silently discards an instruction the author wrote, so a repeat is
    reported instead. An option written as a mapping is descended into, because
    everything under such a name belongs to the option too and a repeat there
    is lost the same way.

    Raises:
        ProcessingError: If a name appears more than once at any level.
    """
    seen: set[tuple[str, str]] = set()
    for key, value in node.value:
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
            _reject_repeated_names(value, f'{prefix}{key.value}.')


def _reject_commented_value(name: str, value: yaml.Node, lines: list[str]) -> None:
    """Refuse a value that YAML cut short at a ``#``.

    Only a plain, unquoted scalar can lose text this way. A quoted value keeps
    its ``#`` and a block scalar is verbatim, so a comment beside either is
    deliberate.

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
    node: yaml.MappingNode,
    text: str,
    names: Collection[str],
) -> None:
    """Refuse an option whose value YAML cut short at a ``#``.

    In YAML a ``#`` outside quotes opens a comment, and the rest of the line
    goes with it. Replacement text is full of Python comments, so the loss is
    likely and the result is plausible enough to ship unnoticed: the option
    keeps whatever came before the ``#``, or falls back to its default when
    nothing did.

    Only the options that take text are checked: an option carrying no value
    has nothing for a comment to eat, and telling its author to quote a value
    they never wrote is advice that leads nowhere. The entries of an option
    written as a mapping are checked too, because everything under such a name
    belongs to the option. Names the tool does not define are somebody else's
    to read, and a comment beside one of those is left alone.

    Raises:
        ProcessingError: If an option's value is followed by a comment.
    """
    lines = text.split('\n')

    for key, value in node.value:
        if not isinstance(key, yaml.ScalarNode) or key.value not in names:
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
    """The header's own source lines, minus those the tool's options occupy.

    The header is shared, so the lines carrying somebody else's options are
    part of the cell and ride into the output with it. Only the lines this
    tool's own options sit on are its to remove.

    An option owns every line from its key down to the next key, which is what
    puts a block scalar's content with the option that opened it. A header with
    no kept lines is replaced whole.
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
    """Whether the header writes one of ``names`` where an option would go.

    In a mapping — a header written the way headers are written — only a key
    names an option, so a name that merely appears in somebody else's value is
    not this tool's to claim.

    Any other shape is a header the author already got wrong, and there the
    reading leans the other way: a missed claim leaves the cell unscrubbed,
    which for ``scrub-omit`` means shipping the solution. So a scalar counts
    when the line it opens on is a name, not only when the value it resolved to
    is one.
    """
    if isinstance(node, yaml.MappingNode):
        return any(_claims_a_name(key, lines, names) for key, _ in node.value)
    if isinstance(node, yaml.SequenceNode):
        return any(_claims_a_name(item, lines, names) for item in node.value)
    if not isinstance(node, yaml.ScalarNode):
        return False
    return node.value in names or _opening_line(node, lines) in names


def _opening_line(node: yaml.Node, lines: list[str]) -> str:
    """The header line on which ``node`` begins, stripped.

    A plain scalar swallows the lines below it, so the value YAML resolves it
    to names nothing even when the author wrote an option name on a line of its
    own: ``scrub-omit`` above a note to self folds into one string. The line the
    scalar starts on still holds what they wrote.
    """
    index = node.start_mark.line
    return lines[index].strip() if 0 <= index < len(lines) else ''


@contextlib.contextmanager
def _loader(text: str) -> Iterator[yaml.SafeLoader]:
    """A YAML loader for ``text``, disposed of once the caller is done.

    Constructing the loader is itself part of reading the text: the reader
    scans the whole string for characters YAML cannot carry as it is built, so
    a malformed header can fail here rather than at the first parsing step.
    """
    loader = yaml.SafeLoader(text)
    try:
        yield loader
    finally:
        loader.dispose()


def _build(
    loader: yaml.SafeLoader,
    node: yaml.Node,
    split: _Split,
    options: Collection[Option],
) -> Header:
    """The Header a composed node graph describes.

    Raises:
        yaml.YAMLError: If the graph's values cannot be built. That is a
            malformed header like one that never parsed, and it is left to the
            caller to say so, so there is one place that turns YAML's
            complaints into advice.
        ProcessingError: If the graph is not one mapping of text names, repeats
            a name, or lets a YAML comment eat an option's value.
    """
    names = {option.name for option in options}
    data = loader.construct_document(node)

    if not isinstance(node, yaml.MappingNode):
        opener = _opening_line(node, split.header.split('\n'))
        if opener in names:
            raise _missing_colon(opener)
        raise _not_a_mapping(data)

    _reject_repeated_names(node)
    _reject_commented_values(
        node,
        split.header,
        frozenset(option.name for option in options if option.takes_text),
    )

    unnamed = [key for key in data if not isinstance(key, str)]
    if unnamed:
        raise ProcessingError(
            'Cell option names must be text, but the header carries '
            f'{unnamed[0]!r}. Quote it if it was meant as a name',
        )

    return Header(
        data,
        _block_styled(node),
        kept=_kept_header(node, split, names),
    )


def _read(
    split: _Split,
    options: Collection[Option],
    names: frozenset[str],
) -> Header:
    """The Header the split's header text describes, from a single parse.

    One loader yields both the node graph and the values, so there is one
    source of truth for what the header says. The graph carries the writing
    that resolved values drop: which scalars are block scalars, where each
    value stopped, and which names were written as keys.

    A header that names none of ``names`` is not this tool's to reject, so a
    complaint about one yields no options instead. Only this tool's own
    complaints are filtered that way: whether the text is YAML at all is not a
    question about ownership, so a failure from YAML passes through untouched.

    Raises:
        yaml.YAMLError: If the header is not well-formed YAML, whether that
            surfaces while parsing it or while building its values.
        ProcessingError: If it is well-formed but names one of ``names``
            wrongly.
    """
    with _loader(split.header) as loader:
        node = loader.get_single_node()
        if node is None:
            return Header()

        try:
            return _build(loader, node, split, options)
        except ProcessingError:
            if _claims_a_name(node, split.header.split('\n'), names):
                raise
            return Header()


def parse_cell_options(
    cell_type: str,
    source: str,
    options: Collection[Option],
) -> Header:
    """Parse the option header at the top of a cell's source.

    Code cells carry the header as a leading run of Quarto ``#|`` lines;
    markdown cells carry it as leading HTML comments. Either way the text is
    one YAML document, and the mapping it holds is returned with its values
    resolved by YAML: ``scrub-omit:`` yields ``None``, ``scrub-clear: hello``
    yields ``'hello'``, and a block scalar yields its lines. Cell types with no
    comment syntax to hide a header in always yield an empty header.

    ``options`` are the options this tool defines. The header is shared with
    whatever else writes in the same comments, so a header that parses but
    names none of them is left alone: a ``#|-----`` divider and a neighbour's
    repeated key both yield no options rather than failing the run. Ownership
    is read off the parsed graph, never guessed from the raw text, so a name
    inside a longer key or in somebody else's value cannot hand this tool a
    header it does not own.

    A header that is not well-formed YAML is reported whether or not it names
    an option, and whether YAML gives up on parsing the text or on building the
    values it parsed. Nothing can say whose such a header is, and the same
    block is YAML to Quarto, so text that malformed is broken for its author
    either way.

    Raises:
        ProcessingError: If the header is not well-formed YAML, or if one
            naming an option is not a mapping of text names, repeats a name, or
            lets a YAML comment eat the value of an option that takes text.
    """
    build = _HEADERS.get(cell_type)
    if build is None:
        # No comment syntax to hide a header in, so the source is all body.
        return Header(body=source)

    split = build(source)
    if not split.header.strip():
        return Header(body=split.body)

    names = frozenset(option.name for option in options)
    try:
        header = _read(split, options, names)
    except yaml.YAMLError as e:
        # YAML could not read the header through, so there is no graph to say
        # whose it is. Guessing from the raw text claims headers that merely
        # look like ours, and staying quiet leaves a cell this tool was told to
        # scrub in the output. Neither is worth it: the header is YAML, Quarto
        # reads the same block as YAML, and text this malformed is broken for
        # whoever else writes here too. Report it.
        raise ProcessingError(_describe(e, split.header)) from e

    # Where the body starts is a property of the source, not of what the header
    # turned out to say, so it is attached here rather than threaded through
    # every path that decides what the header means.
    return replace(header, body=split.body)
