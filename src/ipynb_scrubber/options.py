from __future__ import annotations

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


@dataclass(frozen=True)
class Option:
    """A scrubber option parsed from a cell's option header.

    Attributes:
        inline: Text written on the option line itself. None when the option
            was written with no ``:`` at all (e.g. ``#| scrub-clear``), which
            means "use the configured default".
        block: Content of an attached ``|`` block, or None if there was none.
    """

    inline: str | None = None
    block: str | None = None

    @property
    def value(self) -> str | None:
        """Resolved replacement text, or None to use the configured default."""
        if self.block is not None:
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
    lines in the output, and dropped entirely from the end. The result has no
    trailing newline.
    """
    content = [line for line in lines if line.strip()]
    if not content:
        return ''

    indent = min(len(line) - len(line.lstrip()) for line in content)
    result = [line[indent:] if line.strip() else '' for line in lines]
    while result and not result[-1]:
        result.pop()
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
    return len(text) - len(text.lstrip())


def _build_option(raw_value: str | None, block: str | None) -> Option:
    """Build an Option from a raw inline value and optional block content."""
    if raw_value is None:
        return Option(inline=None, block=block)

    inline = raw_value
    if block is not None:
        # Drop the trailing pipe that opened the block.
        inline = inline.rstrip()[:-1]
    return Option(inline=unescape(inline.strip()), block=block)


def _parse_code_options(source: str) -> dict[str, Option]:
    options: dict[str, Option] = {}
    lines = source.split('\n')
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if not stripped.startswith(CODE_MARKER):
            break

        body = stripped[len(CODE_MARKER) :]
        key_indent = _indent_of(body)
        name, raw_value = _split_option(body.strip())
        index += 1

        block: str | None = None
        if raw_value is not None and opens_block(raw_value):
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
            block = dedent_block(block_lines)

        options[name] = _build_option(raw_value, block)

    return options


def _parse_markdown_options(source: str) -> dict[str, Option]:
    options: dict[str, Option] = {}
    lines = source.split('\n')
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if not stripped.startswith(MARKDOWN_MARKER):
            break

        body = stripped[len(MARKDOWN_MARKER) :].rstrip()
        closed = body.endswith(MARKDOWN_SUFFIX)
        if closed:
            body = body.removesuffix(MARKDOWN_SUFFIX)
        name, raw_value = _split_option(body.strip())
        index += 1

        block: str | None = None
        if not closed and raw_value is not None and opens_block(raw_value):
            block_lines: list[str] = []
            terminated = False
            while index < len(lines):
                if lines[index].strip() == MARKDOWN_SUFFIX:
                    terminated = True
                    index += 1
                    break
                block_lines.append(lines[index])
                index += 1

            if not terminated:
                raise ProcessingError(
                    f"Unterminated block in cell option header ('{name}'): "
                    f"expected a line containing only '{MARKDOWN_SUFFIX}'",
                )
            block = dedent_block(block_lines)

        options[name] = _build_option(raw_value, block)

    return options


def parse_cell_options(cell_type: str, source: str) -> dict[str, Option]:
    """Parse every scrubber option in a cell's option header.

    Code cells use Quarto option syntax (``#| name: value``); markdown cells
    use HTML comments (``<!-- name: value -->``). Other cell types support no
    source-based options and always yield an empty mapping.

    Raises:
        ProcessingError: If a markdown block is not terminated.
    """
    if cell_type == 'code':
        return _parse_code_options(source)
    if cell_type == 'markdown':
        return _parse_markdown_options(source)
    return {}
