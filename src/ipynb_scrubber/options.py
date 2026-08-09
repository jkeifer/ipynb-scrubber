from __future__ import annotations

import re

from collections.abc import Callable
from typing import Any

import yaml

from .exceptions import ProcessingError

CODE_MARKER = '#|'
MARKDOWN_MARKER = '<!--'
MARKDOWN_SUFFIX = '-->'

#: A header line whose value is a block scalar indicator (``|`` or ``>``, with
#: any chomping or explicit-indentation modifier) and nothing else. Used only
#: to decide whether an error message should talk about block indentation.
_BLOCK_INDICATOR = re.compile(r':[^\S\n]*[|>][-+0-9]*[^\S\n]*$', re.MULTILINE)


class _Loader(yaml.SafeLoader):
    """A safe YAML loader that rejects a repeated key.

    YAML resolves a repeated key by keeping the last one. In an option header
    that silently discards an instruction the author wrote, so a repeat is
    reported instead.
    """

    def construct_mapping(
        self,
        node: yaml.MappingNode,
        deep: bool = False,
    ) -> dict[Any, Any]:
        """Build a mapping, raising on a key that appears more than once.

        Raises:
            ProcessingError: If a key is repeated.
        """
        seen: list[Any] = []
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise ProcessingError(
                    f"Duplicate option '{key}' in cell option header",
                )
            seen.append(key)
        return super().construct_mapping(node, deep)


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
    """Parse ``text`` as a single YAML document.

    Raises:
        ProcessingError: If the text is not one well-formed YAML document.
    """
    loader: _Loader | None = None
    try:
        # Construction reads the stream, so it is inside the guard too.
        loader = _Loader(text)
        return loader.get_single_data()
    except yaml.YAMLError as e:
        raise ProcessingError(_describe(e, text)) from e
    finally:
        if loader is not None:
            loader.dispose()


def header_opens_block(cell_type: str, source: str) -> bool:
    """True if the cell's option header opens a block scalar.

    Answers "could an option here have been meant as block content?", which
    lets a caller decide whether advice about block indentation is relevant.
    """
    header = _HEADERS.get(cell_type)
    if header is None:
        return False
    return _BLOCK_INDICATOR.search(header(source)) is not None


def parse_cell_options(cell_type: str, source: str) -> dict[str, Any]:
    """Parse the option header at the top of a cell's source.

    Code cells carry the header as a leading run of Quarto ``#|`` lines;
    markdown cells carry it as leading HTML comments. Either way the text is
    one YAML document, and the mapping it holds is returned with its values
    resolved by YAML: ``scrub-omit:`` yields ``None``, ``scrub-clear: hello``
    yields ``'hello'``, and a block scalar yields its lines. Cell types with no
    comment syntax to hide a header in always yield an empty mapping.

    Raises:
        ProcessingError: If the header is not one well-formed YAML mapping, or
            repeats a key.
    """
    header = _HEADERS.get(cell_type)
    if header is None:
        return {}

    text = header(source)
    if not text.strip():
        return {}

    data = _load(text)
    if data is None:
        return {}

    if not isinstance(data, dict):
        hint = (
            f" Did you mean '{data}:'?"
            if isinstance(data, str) and '\n' not in data
            else ''
        )
        raise ProcessingError(
            "Cell option header must be a mapping of 'name: value' entries, "
            f'but got {type(data).__name__}.{hint}',
        )

    unnamed = [key for key in data if not isinstance(key, str)]
    if unnamed:
        raise ProcessingError(
            'Cell option names must be text, but the header carries '
            f'{unnamed[0]!r}. Quote it if it was meant as a name',
        )

    return data
