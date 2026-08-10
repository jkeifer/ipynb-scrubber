from __future__ import annotations

import contextlib

from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, field
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
    caller whether advice about block indentation is relevant.
    """

    options: dict[str, Any] = field(default_factory=dict)
    block_styled: frozenset[str] = frozenset()


def _code_header(source: str) -> str:
    """The YAML text carried by a code cell's leading run of ``#|`` lines.

    Each marker is stripped along with at most one following space, so that
    content indented relative to the marker keeps that indentation. A blank
    line participates in the header when another ``#|`` line follows it, which
    is what lets a block scalar contain one.
    """
    header: list[str] = []
    pending: list[str] = []

    for line in source.split('\n'):
        text = line.lstrip()
        if text.startswith(CODE_MARKER):
            header.extend(pending)
            pending.clear()
            header.append(text[len(CODE_MARKER) :].removeprefix(' '))
        elif text:
            break
        else:
            pending.append('')

    return '\n'.join(header)


def _markdown_header(source: str) -> str:
    """The YAML text carried by a markdown cell's leading HTML comments.

    A comment is either self-closing (``<!-- scrub-omit: -->``) or spans to a
    line containing only ``-->``. The inner text of each is concatenated into
    one document.

    Raises:
        ProcessingError: If a comment is never closed.
    """
    lines = source.split('\n')
    header: list[str] = []
    pending: list[str] = []
    index = 0

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

    return '\n'.join(header)


_HEADERS: dict[str, Callable[[str], str]] = {
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


def _claims_a_name(node: yaml.Node, text: str, names: Collection[str]) -> bool:
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
        return any(_claims_a_name(key, text, names) for key, _ in node.value)
    if isinstance(node, yaml.SequenceNode):
        return any(_claims_a_name(item, text, names) for item in node.value)
    if not isinstance(node, yaml.ScalarNode):
        return False
    return node.value in names or _opening_line(node, text) in names


def _opening_line(node: yaml.Node, text: str) -> str:
    """The line of ``text`` on which ``node`` begins, stripped.

    A plain scalar swallows the lines below it, so the value YAML resolves it
    to names nothing even when the author wrote an option name on a line of its
    own: ``scrub-omit`` above a note to self folds into one string. The line the
    scalar starts on still holds what they wrote.
    """
    lines = text.split('\n')
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
    text: str,
    options: Collection[Option],
) -> Header:
    """The Header a composed node graph describes.

    Raises:
        ProcessingError: If the graph is not one mapping of text names, repeats
            a name, or lets a YAML comment eat an option's value.
    """
    names = {option.name for option in options}

    try:
        data = loader.construct_document(node)
    except yaml.YAMLError as e:
        raise ProcessingError(_describe(e, text)) from e

    if not isinstance(node, yaml.MappingNode):
        opener = _opening_line(node, text)
        if opener in names:
            raise _missing_colon(opener)
        raise _not_a_mapping(data)

    _reject_repeated_names(node)
    _reject_commented_values(
        node,
        text,
        frozenset(option.name for option in options if option.takes_text),
    )

    unnamed = [key for key in data if not isinstance(key, str)]
    if unnamed:
        raise ProcessingError(
            'Cell option names must be text, but the header carries '
            f'{unnamed[0]!r}. Quote it if it was meant as a name',
        )

    return Header(data, _block_styled(node))


def _read(
    text: str,
    options: Collection[Option],
    names: frozenset[str],
) -> Header:
    """The Header ``text`` describes, from a single parse.

    One loader yields both the node graph and the values, so there is one
    source of truth for what the header says. The graph carries the writing
    that resolved values drop: which scalars are block scalars, where each
    value stopped, and which names were written as keys.

    A header that names none of ``names`` is not this tool's to reject, so a
    complaint about one yields no options instead.

    Raises:
        yaml.YAMLError: If ``text`` is not well-formed YAML.
        ProcessingError: If it is well-formed but names one of ``names``
            wrongly.
    """
    with _loader(text) as loader:
        node = loader.get_single_node()
        if node is None:
            return Header()

        try:
            return _build(loader, node, text, options)
        except ProcessingError:
            if _claims_a_name(node, text, names):
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
    an option. Nothing can say whose it is, and the same block is YAML to
    Quarto, so text that malformed is broken for its author either way.

    Raises:
        ProcessingError: If the header is not well-formed YAML, or if one
            naming an option is not a mapping of text names, repeats a name, or
            lets a YAML comment eat the value of an option that takes text.
    """
    build = _HEADERS.get(cell_type)
    if build is None:
        return Header()

    text = build(source)
    if not text.strip():
        return Header()

    names = frozenset(option.name for option in options)
    try:
        return _read(text, options, names)
    except yaml.YAMLError as e:
        # There is no node graph, so nothing can say whose header this is.
        # Guessing from the raw text claims headers that merely look like ours,
        # and staying quiet leaves a cell this tool was told to scrub in the
        # output. Neither is worth it: the header is YAML, Quarto reads the same
        # block as YAML, and text this malformed is broken for whoever else
        # writes here too. Report it.
        raise ProcessingError(_describe(e, text)) from e
