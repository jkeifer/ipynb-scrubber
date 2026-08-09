from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .exceptions import ProcessingError

CODE_MARKER = '#|'
MARKDOWN_MARKER = '<!--'
MARKDOWN_SUFFIX = '-->'

_ESCAPES = {
    'n': '\n',
    't': '\t',
    '\\': '\\',
    '|': '|',
}


def inline_plus_block_message(name: str) -> str:
    """Shared wording for the inline-text-plus-block conflict.

    Used both by ``Option.single_text`` (e.g. ``scrub-clear``) and by
    ``actions._note_action`` (``scrub-note``), so a user hitting the same
    mistake on either option gets identical advice.
    """
    return (
        f"Option '{name}' has both inline text and a block: "
        "the trailing '|' opens a block. Use one or the other, or "
        "escape a literal pipe as '\\|'"
    )


@dataclass(frozen=True)
class Option:
    """A scrubber option parsed from a cell's option header.

    Attributes:
        name: The option name, used in error messages.
        raw_inline: Text written on the option line itself, verbatim —
            escape sequences are NOT expanded. None when the option was
            written with no ``:`` at all (e.g. ``#| scrub-clear``), which
            means "use the configured default".
        block: Content of an attached ``|`` block, or None if there was none.

    Escapes are expanded lazily, by ``inline`` and ``fields``, so that
    consumers which split the value on ``|`` split *before* ``\\|`` has
    become an ordinary pipe.
    """

    name: str
    raw_inline: str | None = None
    block: str | None = None

    @property
    def inline(self) -> str | None:
        """The inline value, stripped and unescaped."""
        if self.raw_inline is None:
            return None
        return unescape(self.raw_inline.strip())

    def fields(self, count: int) -> list[str]:
        """Split the inline value on unescaped pipes into at most ``count`` parts.

        Each part is stripped and unescaped afterwards, so ``\\|`` survives
        as a literal pipe inside a field instead of acting as a separator.
        """
        if self.raw_inline is None:
            return []

        parts: list[str] = []
        current: list[str] = []
        index = 0
        while index < len(self.raw_inline):
            char = self.raw_inline[index]
            if char == '\\' and index + 1 < len(self.raw_inline):
                current.append(self.raw_inline[index : index + 2])
                index += 2
                continue
            if char == '|' and len(parts) < count - 1:
                parts.append(''.join(current))
                current = []
                index += 1
                continue
            current.append(char)
            index += 1
        parts.append(''.join(current))

        return [unescape(part.strip()) for part in parts]

    def single_text(self) -> str | None:
        """The one text value this option carries, or None for the default.

        Raises:
            ProcessingError: If inline text and a block are both present.
        """
        if self.block is not None:
            if self.raw_inline and self.raw_inline.strip():
                raise ProcessingError(inline_plus_block_message(self.name))
            return self.block
        return self.inline


def unescape(value: str) -> str:
    """Expand escape sequences in an inline option value.

    Recognises ``\\n``, ``\\t``, ``\\\\`` and ``\\|``. Any other backslash
    sequence is passed through untouched, so regex literals such as
    ``r"\\d+"`` survive without doubling.
    """
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == '\\' and index + 1 < len(value) and value[index + 1] in _ESCAPES:
            result.append(_ESCAPES[value[index + 1]])
            index += 2
            continue
        result.append(char)
        index += 1
    return ''.join(result)


def opens_block(value: str) -> bool:
    """True if an option value ends with an unescaped pipe."""
    stripped = value.rstrip()
    if not stripped.endswith('|'):
        return False

    backslashes = 0
    index = len(stripped) - 2
    while index >= 0 and stripped[index] == '\\':
        backslashes += 1
        index -= 1
    return backslashes % 2 == 0


def dedent_block(lines: list[str]) -> str:
    """Join block content lines, dedented by their minimum indentation.

    Blank lines are ignored when computing the minimum, preserved as empty
    lines in the interior, and dropped from both ends. The result has no
    trailing newline.
    """
    expanded = [line.expandtabs() for line in lines]
    content = [line for line in expanded if line.strip()]
    if not content:
        return ''

    indent = min(len(line) - len(line.lstrip()) for line in content)
    result = [line[indent:] if line.strip() else '' for line in expanded]
    while result and not result[-1]:
        result.pop()
    while result and not result[0]:
        result.pop(0)
    return '\n'.join(result)


def _split_option(text: str) -> tuple[str, str | None]:
    """Split an option header body into (name, raw_value).

    raw_value is None when there is no ``:`` at all.
    """
    if ':' in text:
        name, _, raw_value = text.partition(':')
        return name.strip(), raw_value
    return text, None


def _indent_of(text: str) -> int:
    """Indentation width, counting a tab as its expanded width."""
    expanded = text.expandtabs()
    return len(expanded) - len(expanded.lstrip())


def _build_option(name: str, raw_value: str | None, block: str | None) -> Option:
    """Build an Option from a raw inline value and optional block content."""
    if raw_value is None:
        return Option(name=name, raw_inline=None, block=block)

    raw_inline = raw_value
    if block is not None:
        # Drop the trailing pipe that opened the block.
        raw_inline = raw_inline.rstrip()[:-1]
    return Option(name=name, raw_inline=raw_inline, block=block)


@dataclass(frozen=True)
class Dialect:
    """How one cell type spells its option header.

    Attributes:
        header: Maps a stripped source line to (option body, may_open_block),
            or None if the line is not a header line at all.
        read_block: Given all lines, the index just past the header line, and
            the header's own indent, returns (block content lines, next index).
    """

    header: Callable[[str], tuple[str, bool] | None]
    read_block: Callable[[list[str], int, int], tuple[list[str], int]]


def _code_header(stripped: str) -> tuple[str, bool] | None:
    if not stripped.startswith(CODE_MARKER):
        return None
    return stripped[len(CODE_MARKER) :], True


def _markdown_header(stripped: str) -> tuple[str, bool] | None:
    if not stripped.startswith(MARKDOWN_MARKER):
        return None
    body = stripped[len(MARKDOWN_MARKER) :].rstrip()
    if body.endswith(MARKDOWN_SUFFIX):
        # A self-closing comment cannot open a block.
        return body.removesuffix(MARKDOWN_SUFFIX), False
    return body, True


def _read_indented_block(
    lines: list[str],
    index: int,
    key_indent: int,
) -> tuple[list[str], int]:
    block_lines: list[str] = []
    while index < len(lines):
        candidate = lines[index].strip()
        if not candidate.startswith(CODE_MARKER):
            break

        content = candidate[len(CODE_MARKER) :]
        if not content.strip():
            block_lines.append('')
            index += 1
            continue
        if _indent_of(content) <= key_indent:
            break

        block_lines.append(content)
        index += 1
    return block_lines, index


def _read_sentinel_block(
    lines: list[str],
    index: int,
    key_indent: int,
) -> tuple[list[str], int]:
    block_lines: list[str] = []
    while index < len(lines):
        if lines[index].strip() == MARKDOWN_SUFFIX:
            return block_lines, index + 1
        block_lines.append(lines[index])
        index += 1

    raise ProcessingError(
        'Unterminated block in cell option header: '
        f"expected a line containing only '{MARKDOWN_SUFFIX}'",
    )


_DIALECTS = {
    'code': Dialect(header=_code_header, read_block=_read_indented_block),
    'markdown': Dialect(header=_markdown_header, read_block=_read_sentinel_block),
}


def _parse(source: str, dialect: Dialect) -> dict[str, Option]:
    options: dict[str, Option] = {}
    lines = source.split('\n')
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue

        parsed = dialect.header(stripped)
        if parsed is None:
            break
        body, may_open_block = parsed

        key_indent = _indent_of(body)
        name, raw_value = _split_option(body.strip())
        index += 1

        block: str | None = None
        if may_open_block and raw_value is not None and opens_block(raw_value):
            block_lines, index = dialect.read_block(lines, index, key_indent)
            block = dedent_block(block_lines)

        if name in options:
            raise ProcessingError(
                f"Duplicate option '{name}' in cell option header",
            )
        options[name] = _build_option(name, raw_value, block)

    return options


def parse_cell_options(cell_type: str, source: str) -> dict[str, Option]:
    """Parse every scrubber option in a cell's option header.

    Code cells use Quarto option syntax (``#| name: value``); markdown cells
    use HTML comments (``<!-- name: value -->``). Other cell types support no
    source-based options and always yield an empty mapping.

    Raises:
        ProcessingError: If a block is malformed or an option name repeats.
    """
    dialect = _DIALECTS.get(cell_type)
    if dialect is None:
        return {}
    return _parse(source, dialect)
