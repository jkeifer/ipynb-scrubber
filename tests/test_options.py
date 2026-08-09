import re

import pytest

from ipynb_scrubber.exceptions import ProcessingError
from ipynb_scrubber.options import (
    Option,
    dedent_block,
    opens_block,
    parse_cell_options,
    unescape,
)


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        (r'a\nb', 'a\nb'),
        (r'a\tb', 'a\tb'),
        (r'a\\b', 'a\\b'),
        (r'a\|b', 'a|b'),
        (r're.match(r"\d+")', r're.match(r"\d+")'),
        (r'trailing backslash \\', 'trailing backslash \\'),
        ('no escapes', 'no escapes'),
        ('', ''),
    ],
)
def test_unescape(raw: str, expected: str) -> None:
    assert unescape(raw) == expected


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('|', True),
        ('ex-1 |', True),
        ('|   ', True),
        ('hello', False),
        ('', False),
        (r'\|', False),
        (r'a\\|', True),
        ('a | b', False),
    ],
)
def test_opens_block(raw: str, expected: bool) -> None:
    assert opens_block(raw) is expected


def test_dedent_block_uses_minimum_indent() -> None:
    assert dedent_block(['      # TODO', '  x = 1']) == '    # TODO\nx = 1'


def test_dedent_block_preserves_interior_blanks() -> None:
    assert dedent_block(['  a', '', '  b']) == 'a\n\nb'


def test_dedent_block_drops_trailing_blanks() -> None:
    assert dedent_block(['  a', '', '']) == 'a'


def test_dedent_block_empty() -> None:
    assert dedent_block([]) == ''
    assert dedent_block(['', '  ']) == ''


def test_code_option_no_value() -> None:
    options = parse_cell_options('code', '#| scrub-clear\nprint("x")')
    assert options == {
        'scrub-clear': Option(name='scrub-clear', raw_inline=None, block=None),
    }
    assert options['scrub-clear'].single_text() is None


def test_code_option_inline_value() -> None:
    options = parse_cell_options('code', '#| scrub-clear: hello\nprint("x")')
    assert options['scrub-clear'].single_text() == 'hello'


def test_code_option_empty_value() -> None:
    options = parse_cell_options('code', '#| scrub-clear:\nprint("x")')
    assert options['scrub-clear'].single_text() == ''


def test_code_option_inline_escapes() -> None:
    options = parse_cell_options('code', r'#| scrub-clear: a\nb')
    assert options['scrub-clear'].single_text() == 'a\nb'


def test_code_block() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   def add(a, b):',
            '#|       pass',
            'def add(a, b):',
            '    return a + b',
        ],
    )
    options = parse_cell_options('code', source)
    assert options['scrub-clear'].single_text() == 'def add(a, b):\n    pass'


def test_code_block_is_verbatim() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            r'#|   re.match(r"\d+\n", s)',
        ],
    )
    options = parse_cell_options('code', source)
    assert options['scrub-clear'].single_text() == r're.match(r"\d+\n", s)'


def test_code_block_ragged_dedents_by_minimum() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|       # TODO: the hard part',
            '#|   x = 1',
        ],
    )
    options = parse_cell_options('code', source)
    assert options['scrub-clear'].single_text() == '    # TODO: the hard part\nx = 1'


def test_code_block_interior_blank_line() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   a',
            '#|',
            '#|   b',
        ],
    )
    options = parse_cell_options('code', source)
    assert options['scrub-clear'].single_text() == 'a\n\nb'


def test_code_block_empty() -> None:
    options = parse_cell_options('code', '#| scrub-clear: |\nprint("x")')
    assert options['scrub-clear'].single_text() == ''


def test_code_block_terminated_by_option_at_key_indent() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   line one',
            '#|   line two',
            '#| scrub-omit',
        ],
    )
    options = parse_cell_options('code', source)
    assert options['scrub-clear'].single_text() == 'line one\nline two'
    assert 'scrub-omit' in options


def test_code_block_content_is_not_parsed_as_options() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   scrub-omit',
        ],
    )
    options = parse_cell_options('code', source)
    assert options['scrub-clear'].single_text() == 'scrub-omit'
    assert 'scrub-omit' not in options


def test_code_block_terminated_by_non_option_line() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   line one',
            'print("x")',
        ],
    )
    options = parse_cell_options('code', source)
    assert options['scrub-clear'].single_text() == 'line one'


def test_code_note_block_strips_one_pipe() -> None:
    source = '\n'.join(
        [
            '#| scrub-note: ex-1 |',
            '#|   def add(a, b):',
            '#|       pass',
        ],
    )
    options = parse_cell_options('code', source)
    assert options['scrub-note'].inline == 'ex-1'
    assert options['scrub-note'].block == 'def add(a, b):\n    pass'


def test_code_escaped_pipe_does_not_open_block() -> None:
    source = '\n'.join(
        [
            r'#| scrub-clear: # fill in \|',
            '#|   not a block',
        ],
    )
    options = parse_cell_options('code', source)
    assert options['scrub-clear'].single_text() == '# fill in |'
    assert options['scrub-clear'].block is None


def test_code_options_survive_blank_lines_in_the_header() -> None:
    """Blank lines before and between code option lines are skipped, not fatal."""
    source = '\n'.join(
        [
            '',
            '#| scrub-clear: hello',
            '',
            '#| scrub-omit',
            'print("x")',
        ],
    )
    options = parse_cell_options('code', source)
    assert options['scrub-clear'].single_text() == 'hello'
    assert 'scrub-omit' in options


def test_multiple_options() -> None:
    options = parse_cell_options('code', '#| scrub-clear\n#| scrub-omit\nprint("x")')
    assert set(options) == {'scrub-clear', 'scrub-omit'}


def test_raw_cell_has_no_options() -> None:
    assert parse_cell_options('raw', '#| scrub-clear') == {}


def test_markdown_option_no_value() -> None:
    options = parse_cell_options('markdown', '<!-- scrub-clear -->\n## Q')
    assert options['scrub-clear'].single_text() is None


def test_markdown_option_inline_value() -> None:
    options = parse_cell_options('markdown', '<!-- scrub-clear: **Answer** -->\n## Q')
    assert options['scrub-clear'].single_text() == '**Answer**'


def test_markdown_block() -> None:
    source = '\n'.join(
        [
            '<!-- scrub-clear: |',
            '  **Write your answer here**',
            '',
            '  Show your work.',
            '-->',
            '## Solution',
        ],
    )
    options = parse_cell_options('markdown', source)
    assert options['scrub-clear'].single_text() == (
        '**Write your answer here**\n\nShow your work.'
    )


def test_markdown_block_unterminated_raises() -> None:
    source = '\n'.join(
        [
            '<!-- scrub-clear: |',
            '  never closed',
        ],
    )
    with pytest.raises(ProcessingError, match='Unterminated'):
        parse_cell_options('markdown', source)


def test_markdown_block_unterminated_message_does_not_claim_an_option() -> None:
    """The parser is tag-agnostic, so the message must not call the name an option."""
    source = '\n'.join(
        [
            '<!-- schedule: a | b |',
            '  never closed',
        ],
    )
    expected = (
        "Unterminated block in cell option header ('schedule'): "
        "expected a line containing only '-->'"
    )
    with pytest.raises(ProcessingError, match=re.escape(expected)):
        parse_cell_options('markdown', source)


def test_markdown_closed_comment_is_never_a_block() -> None:
    options = parse_cell_options('markdown', '<!-- scrub-clear: | -->\n## Q')
    assert options['scrub-clear'].single_text() == '|'
    assert options['scrub-clear'].block is None


def test_markdown_block_content_is_not_parsed_as_options() -> None:
    source = '\n'.join(
        [
            '<!-- scrub-clear: |',
            '  <!-- scrub-omit -->',
            '-->',
        ],
    )
    options = parse_cell_options('markdown', source)
    assert options['scrub-clear'].single_text() == '<!-- scrub-omit -->'
    assert 'scrub-omit' not in options


@pytest.mark.parametrize(
    ('raw', 'count', 'expected'),
    [
        ('ex-1', 2, ['ex-1']),
        ('ex-1 | text', 2, ['ex-1', 'text']),
        ('ex-1|text', 2, ['ex-1', 'text']),
        (r'a\|b', 2, ['a|b']),
        (r'a\|b | text', 2, ['a|b', 'text']),
        ('a | b | c', 2, ['a', 'b | c']),
        (r'\|only', 2, ['|only']),
        (None, 2, []),
    ],
)
def test_option_fields_splits_on_unescaped_pipes(raw, count, expected):
    assert Option(name='scrub-note', raw_inline=raw).fields(count) == expected


def test_option_single_text_prefers_block():
    assert (
        Option(name='scrub-clear', raw_inline='', block='body').single_text() == 'body'
    )


def test_option_single_text_unescapes_inline():
    assert Option(name='scrub-clear', raw_inline=r'a\nb').single_text() == 'a\nb'


def test_option_single_text_none_when_no_colon():
    assert Option(name='scrub-clear').single_text() is None


def test_option_single_text_rejects_inline_plus_block():
    option = Option(name='scrub-clear', raw_inline='hello', block='body')
    with pytest.raises(ProcessingError, match=r'scrub-clear'):
        option.single_text()
