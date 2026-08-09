from __future__ import annotations

from collections.abc import Callable, Collection
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
        body = text[len(MARKDOWN_MARKER) :].rstrip()
        index += 1

        if body.endswith(MARKDOWN_SUFFIX):
            header.append(body.removesuffix(MARKDOWN_SUFFIX).rstrip().removeprefix(' '))
            continue

        header.append(body.removeprefix(' '))
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
        if problem:
            return f'Invalid cell option header: {problem} (line {mark.line + 1})'

    return f'Invalid cell option header: {error}'


def _load(text: str) -> Any:
    """Resolve ``text`` into the Python values its YAML describes.

    Raises:
        ProcessingError: If the text is not one well-formed YAML document.
    """
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ProcessingError(_describe(e, text)) from e


def _not_a_mapping(text: str) -> ProcessingError:
    """The error for a header that holds something other than a mapping.

    A lone name — ``#| scrub-omit`` — is a bare string, and the fix is the
    colon it is missing, so the message offers it.
    """
    data = _load(text)
    hint = (
        f" Did you mean '{data}:'?"
        if isinstance(data, str) and '\n' not in data
        else ''
    )
    return ProcessingError(
        "Cell option header must be a mapping of 'name: value' entries, "
        f'but got {type(data).__name__}.{hint}',
    )


def _reject_repeated_names(node: yaml.MappingNode) -> None:
    """Refuse a name that the header carries more than once.

    YAML resolves a repeated name by keeping the last one. In an option header
    that silently discards an instruction the author wrote, so a repeat is
    reported instead.

    Raises:
        ProcessingError: If a name appears more than once.
    """
    seen: set[tuple[str, str]] = set()
    for key, _ in node.value:
        if not isinstance(key, yaml.ScalarNode):
            continue
        # The tag is part of the identity: quoted '12' and bare 12 are the
        # same characters but different names.
        identity = (key.tag, key.value)
        if identity in seen:
            raise ProcessingError(
                f"Duplicate option '{key.value}' in cell option header",
            )
        seen.add(identity)


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

    The options this tool defines are checked, and so are the entries of an
    option written as a mapping, because everything under such a name belongs
    to the option too. Names the tool does not define are somebody else's to
    read, and a comment beside one of those is left alone.

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


def parse_cell_options(
    cell_type: str,
    source: str,
    names: Collection[str],
) -> Header:
    """Parse the option header at the top of a cell's source.

    Code cells carry the header as a leading run of Quarto ``#|`` lines;
    markdown cells carry it as leading HTML comments. Either way the text is
    one YAML document, and the mapping it holds is returned with its values
    resolved by YAML: ``scrub-omit:`` yields ``None``, ``scrub-clear: hello``
    yields ``'hello'``, and a block scalar yields its lines. Cell types with no
    comment syntax to hide a header in always yield an empty header.

    ``names`` is the set of option names this tool defines. The header is
    shared with whatever else writes in the same comments, so text that holds
    no such name is left alone: a ``#|-----`` divider or a ``#| fig-cap: A: B``
    that YAML cannot read yields no options rather than failing the run.

    Raises:
        ProcessingError: If a header carrying one of ``names`` is not one
            well-formed YAML mapping, repeats a name, or lets a YAML comment
            eat an option's value.
    """
    build = _HEADERS.get(cell_type)
    if build is None:
        return Header()

    text = build(source)
    if not text.strip():
        return Header()

    ours = any(name in text for name in names)

    try:
        # The node graph carries the writing that resolved values drop: which
        # scalars are block scalars, and where each value stopped.
        node = yaml.compose(text)
    except yaml.YAMLError as e:
        if not ours:
            return Header()
        raise ProcessingError(_describe(e, text)) from e

    if node is None:
        return Header()

    if not isinstance(node, yaml.MappingNode):
        if not ours:
            return Header()
        raise _not_a_mapping(text)

    _reject_repeated_names(node)
    _reject_commented_values(node, text, names)
    block_styled = _block_styled(node)

    options = _load(text)

    unnamed = [key for key in options if not isinstance(key, str)]
    if unnamed:
        raise ProcessingError(
            'Cell option names must be text, but the header carries '
            f'{unnamed[0]!r}. Quote it if it was meant as a name',
        )

    return Header(options, block_styled)
