import re

import pytest

from ipynb_scrubber.exceptions import ProcessingError
from ipynb_scrubber.options import header_opens_block, parse_cell_options


def test_code_option_with_no_value_is_null() -> None:
    options = parse_cell_options('code', '#| scrub-clear:\nprint("x")')
    assert options == {'scrub-clear': None}


def test_code_option_inline_value() -> None:
    options = parse_cell_options('code', '#| scrub-clear: hello\nprint("x")')
    assert options == {'scrub-clear': 'hello'}


def test_code_option_quoted_value_keeps_a_leading_hash() -> None:
    """An unquoted '#' opens a YAML comment, so replacement text is quoted."""
    options = parse_cell_options('code', '#| scrub-clear: "# TODO"\nprint("x")')
    assert options == {'scrub-clear': '# TODO'}


def test_code_option_empty_string() -> None:
    options = parse_cell_options('code', '#| scrub-clear: ""\nprint("x")')
    assert options == {'scrub-clear': ''}


def test_code_option_value_keeps_its_yaml_type() -> None:
    """'no' resolves to a boolean; the caller decides whether that is usable."""
    options = parse_cell_options('code', '#| scrub-clear: no\nprint("x")')
    assert options == {'scrub-clear': False}


def test_code_block_scalar() -> None:
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
    assert options == {'scrub-clear': 'def add(a, b):\n    pass'}


def test_code_block_scalar_is_verbatim() -> None:
    """Backslashes inside a block scalar are content, so regexes survive."""
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            r'#|   re.match(r"\d+", s)',
        ],
    )
    options = parse_cell_options('code', source)
    assert options == {'scrub-clear': r're.match(r"\d+", s)'}


def test_code_block_scalar_keeps_a_marked_blank_line() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   a',
            '#|',
            '#|   b',
        ],
    )
    options = parse_cell_options('code', source)
    assert options == {'scrub-clear': 'a\n\nb'}


def test_code_block_scalar_keeps_an_unmarked_blank_line() -> None:
    """A blank line joins the header when another '#|' line follows it."""
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   a',
            '',
            '#|   b',
            'print("x")',
        ],
    )
    options = parse_cell_options('code', source)
    assert options == {'scrub-clear': 'a\n\nb'}


def test_code_block_scalar_with_no_content() -> None:
    options = parse_cell_options('code', '#| scrub-clear: |\nprint("x")')
    assert options == {'scrub-clear': ''}


def test_header_ends_at_the_first_ordinary_line() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: hello',
            'print("x")',
            '#| scrub-omit:',
        ],
    )
    options = parse_cell_options('code', source)
    assert options == {'scrub-clear': 'hello'}


def test_block_scalar_content_is_not_read_as_options() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   scrub-omit:',
        ],
    )
    options = parse_cell_options('code', source)
    assert options == {'scrub-clear': 'scrub-omit:'}


def test_quarto_options_are_siblings() -> None:
    source = '\n'.join(
        [
            '#| label: fig-one',
            '#| echo: false',
            '#| scrub-clear: hello',
            'print("x")',
        ],
    )
    options = parse_cell_options('code', source)
    assert options == {
        'label': 'fig-one',
        'echo': False,
        'scrub-clear': 'hello',
    }


def test_note_mapping_form() -> None:
    source = '\n'.join(
        [
            '#| scrub-note:',
            '#|   id: exercise-1',
            '#|   text: |',
            '#|     def solve():',
            '#|         pass',
            'print("x")',
        ],
    )
    options = parse_cell_options('code', source)
    assert options == {
        'scrub-note': {'id': 'exercise-1', 'text': 'def solve():\n    pass'},
    }


def test_indented_header_lines_are_recognised() -> None:
    options = parse_cell_options('code', '    #| scrub-clear: hello\n    print("x")')
    assert options == {'scrub-clear': 'hello'}


def test_leading_blank_lines_are_skipped() -> None:
    options = parse_cell_options('code', '\n\n#| scrub-clear: hello\nprint("x")')
    assert options == {'scrub-clear': 'hello'}


def test_cell_without_a_header() -> None:
    assert parse_cell_options('code', 'print("x")') == {}


def test_raw_cell_has_no_options() -> None:
    assert parse_cell_options('raw', '#| scrub-clear:') == {}


def test_markdown_self_closing_comment() -> None:
    options = parse_cell_options('markdown', '<!-- scrub-clear: -->\n## Q')
    assert options == {'scrub-clear': None}


def test_markdown_self_closing_comment_with_value() -> None:
    options = parse_cell_options(
        'markdown',
        '<!-- scrub-clear: "**Answer**" -->\n## Q',
    )
    assert options == {'scrub-clear': '**Answer**'}


def test_markdown_consecutive_self_closing_comments() -> None:
    source = '\n'.join(
        [
            '<!-- echo: false -->',
            '<!-- scrub-clear: hello -->',
            '## Q',
        ],
    )
    options = parse_cell_options('markdown', source)
    assert options == {'echo': False, 'scrub-clear': 'hello'}


def test_markdown_multi_line_comment() -> None:
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
    assert options == {
        'scrub-clear': '**Write your answer here**\n\nShow your work.',
    }


def test_markdown_unterminated_comment_raises() -> None:
    source = '\n'.join(
        [
            '<!-- scrub-clear: |',
            '  never closed',
        ],
    )
    expected = (
        'Unterminated comment in cell option header: '
        "expected a line containing only '-->'"
    )
    with pytest.raises(ProcessingError, match=re.escape(expected)):
        parse_cell_options('markdown', source)


def test_markdown_comment_content_is_not_read_as_options() -> None:
    source = '\n'.join(
        [
            '<!-- scrub-clear: |',
            '  <!-- scrub-omit: -->',
            '-->',
        ],
    )
    options = parse_cell_options('markdown', source)
    assert options == {'scrub-clear': '<!-- scrub-omit: -->'}


def test_duplicate_option_name_raises() -> None:
    with pytest.raises(ProcessingError, match=r"Duplicate option 'scrub-clear'"):
        parse_cell_options('code', '#| scrub-clear: first\n#| scrub-clear: second')


def test_header_that_is_not_a_mapping_raises() -> None:
    with pytest.raises(ProcessingError, match='must be a mapping'):
        parse_cell_options('code', '#| - one\n#| - two')


def test_option_without_a_colon_raises_with_a_hint() -> None:
    """A lone name is a bare string, and the fix is the colon it is missing."""
    with pytest.raises(ProcessingError, match=re.escape("Did you mean 'scrub-omit:'?")):
        parse_cell_options('code', '#| scrub-omit\nprint("x")')


def test_non_text_option_name_raises() -> None:
    with pytest.raises(ProcessingError, match='option names must be text'):
        parse_cell_options('code', '#| 12: hello')


def test_tab_in_the_indentation_raises_a_targeted_error() -> None:
    source = '#| scrub-clear: |\n#|\tdef add(a, b):\n#|\t    pass'
    with pytest.raises(
        ProcessingError,
        match=r'contains a tab.*indent it with spaces',
    ):
        parse_cell_options('code', source)


def test_malformed_header_raises_without_leaking_the_yaml_error() -> None:
    with pytest.raises(ProcessingError, match='Invalid cell option header') as exc:
        parse_cell_options('code', '#| scrub-clear: TODO: fix')
    assert 'line 1' in str(exc.value)


def test_header_of_only_comments_yields_no_options() -> None:
    assert parse_cell_options('code', '#| # just a note to self\nprint("x")') == {}


def test_unreadable_header_raises_without_leaking_the_yaml_error() -> None:
    """A failure YAML cannot place still arrives as a ProcessingError."""
    with pytest.raises(ProcessingError, match='Invalid cell option header'):
        parse_cell_options('code', '#| scrub-clear: "\x00"')


def test_header_opens_block_detects_a_block_indicator() -> None:
    assert header_opens_block('code', '#| scrub-clear: |\n#|   a') is True
    assert header_opens_block('code', '#| scrub-clear: |-\n#|   a') is True
    assert header_opens_block('markdown', '<!-- scrub-clear: |\n  a\n-->') is True


def test_header_opens_block_is_false_without_one() -> None:
    assert header_opens_block('code', '#| scrub-clear: hello') is False
    assert header_opens_block('code', '#| scrub-clear: "a | b"') is False
    assert header_opens_block('raw', '#| scrub-clear: |') is False
