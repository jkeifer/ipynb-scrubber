import re

from typing import Any

import pytest

from ipynb_scrubber.exceptions import ProcessingError
from ipynb_scrubber.options import parse_cell_options

#: The option names the tool defines, under their default spellings.
NAMES = ('scrub-clear', 'scrub-omit', 'scrub-note')


def options(cell_type: str, source: str) -> dict[str, Any]:
    """The option mapping a cell's header carries."""
    return parse_cell_options(cell_type, source, NAMES).options


def block_styled(cell_type: str, source: str) -> frozenset[str]:
    """The names of the options a cell's header writes as a block scalar."""
    return parse_cell_options(cell_type, source, NAMES).block_styled


def test_code_option_with_no_value_is_null() -> None:
    result = options('code', '#| scrub-clear:\nprint("x")')
    assert result == {'scrub-clear': None}


def test_code_option_inline_value() -> None:
    result = options('code', '#| scrub-clear: hello\nprint("x")')
    assert result == {'scrub-clear': 'hello'}


def test_code_option_quoted_value_keeps_a_leading_hash() -> None:
    """An unquoted '#' opens a YAML comment, so replacement text is quoted."""
    result = options('code', '#| scrub-clear: "# TODO"\nprint("x")')
    assert result == {'scrub-clear': '# TODO'}


def test_code_option_empty_string() -> None:
    result = options('code', '#| scrub-clear: ""\nprint("x")')
    assert result == {'scrub-clear': ''}


def test_code_option_value_keeps_its_yaml_type() -> None:
    """'no' resolves to a boolean; the caller decides whether that is usable."""
    result = options('code', '#| scrub-clear: no\nprint("x")')
    assert result == {'scrub-clear': False}


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
    result = options('code', source)
    assert result == {'scrub-clear': 'def add(a, b):\n    pass'}


def test_code_block_scalar_is_verbatim() -> None:
    """Backslashes inside a block scalar are content, so regexes survive."""
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            r'#|   re.match(r"\d+", s)',
        ],
    )
    result = options('code', source)
    assert result == {'scrub-clear': r're.match(r"\d+", s)'}


def test_code_block_scalar_keeps_a_marked_blank_line() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   a',
            '#|',
            '#|   b',
        ],
    )
    result = options('code', source)
    assert result == {'scrub-clear': 'a\n\nb'}


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
    result = options('code', source)
    assert result == {'scrub-clear': 'a\n\nb'}


def test_code_block_scalar_with_no_content() -> None:
    result = options('code', '#| scrub-clear: |\nprint("x")')
    assert result == {'scrub-clear': ''}


def test_header_ends_at_the_first_ordinary_line() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: hello',
            'print("x")',
            '#| scrub-omit:',
        ],
    )
    result = options('code', source)
    assert result == {'scrub-clear': 'hello'}


def test_block_scalar_content_is_not_read_as_options() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   scrub-omit:',
        ],
    )
    result = options('code', source)
    assert result == {'scrub-clear': 'scrub-omit:'}


def test_quarto_options_are_siblings() -> None:
    source = '\n'.join(
        [
            '#| label: fig-one',
            '#| echo: false',
            '#| scrub-clear: hello',
            'print("x")',
        ],
    )
    result = options('code', source)
    assert result == {
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
    result = options('code', source)
    assert result == {
        'scrub-note': {'id': 'exercise-1', 'text': 'def solve():\n    pass'},
    }


def test_indented_header_lines_are_recognised() -> None:
    result = options('code', '    #| scrub-clear: hello\n    print("x")')
    assert result == {'scrub-clear': 'hello'}


def test_leading_blank_lines_are_skipped() -> None:
    result = options('code', '\n\n#| scrub-clear: hello\nprint("x")')
    assert result == {'scrub-clear': 'hello'}


def test_cell_without_a_header() -> None:
    assert options('code', 'print("x")') == {}


def test_raw_cell_has_no_options() -> None:
    assert options('raw', '#| scrub-clear:') == {}


def test_markdown_self_closing_comment() -> None:
    result = options('markdown', '<!-- scrub-clear: -->\n## Q')
    assert result == {'scrub-clear': None}


def test_markdown_self_closing_comment_with_value() -> None:
    result = options(
        'markdown',
        '<!-- scrub-clear: "**Answer**" -->\n## Q',
    )
    assert result == {'scrub-clear': '**Answer**'}


def test_markdown_consecutive_self_closing_comments() -> None:
    source = '\n'.join(
        [
            '<!-- echo: false -->',
            '<!-- scrub-clear: hello -->',
            '## Q',
        ],
    )
    result = options('markdown', source)
    assert result == {'echo': False, 'scrub-clear': 'hello'}


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
    result = options('markdown', source)
    assert result == {
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
        options('markdown', source)


def test_markdown_comment_content_is_not_read_as_options() -> None:
    source = '\n'.join(
        [
            '<!-- scrub-clear: |',
            '  <!-- scrub-omit: -->',
            '-->',
        ],
    )
    result = options('markdown', source)
    assert result == {'scrub-clear': '<!-- scrub-omit: -->'}


def test_duplicate_option_name_raises() -> None:
    with pytest.raises(ProcessingError, match=r"Duplicate option 'scrub-clear'"):
        options('code', '#| scrub-clear: first\n#| scrub-clear: second')


def test_header_that_is_not_a_mapping_raises() -> None:
    with pytest.raises(ProcessingError, match='must be a mapping'):
        options('code', '#| - scrub-omit\n#| - two')


def test_option_without_a_colon_raises_with_a_hint() -> None:
    """A lone name is a bare string, and the fix is the colon it is missing."""
    with pytest.raises(ProcessingError, match=re.escape("Did you mean 'scrub-omit:'?")):
        options('code', '#| scrub-omit\nprint("x")')


def test_non_text_option_name_raises() -> None:
    with pytest.raises(ProcessingError, match='option names must be text'):
        options('code', '#| 12: hello')


def test_tab_in_the_indentation_raises_a_targeted_error() -> None:
    source = '#| scrub-clear: |\n#|\tdef add(a, b):\n#|\t    pass'
    with pytest.raises(
        ProcessingError,
        match=r'contains a tab.*indent it with spaces',
    ):
        options('code', source)


def test_malformed_header_raises_without_leaking_the_yaml_error() -> None:
    with pytest.raises(ProcessingError, match='Invalid cell option header') as exc:
        options('code', '#| scrub-clear: TODO: fix')
    assert 'line 1' in str(exc.value)


def test_header_of_only_comments_yields_no_options() -> None:
    assert options('code', '#| # just a note to self\nprint("x")') == {}


def test_unreadable_header_raises_without_leaking_the_yaml_error() -> None:
    """A failure YAML cannot place still arrives as a ProcessingError."""
    with pytest.raises(ProcessingError, match='Invalid cell option header'):
        options('code', '#| scrub-clear: "\x00"')


def test_block_styled_names_the_options_written_as_a_block() -> None:
    assert block_styled('code', '#| scrub-clear: |\n#|   a') == {'scrub-clear'}
    assert block_styled('code', '#| scrub-clear: |-\n#|   a') == {'scrub-clear'}
    assert block_styled('code', '#| scrub-clear: >\n#|   a') == {'scrub-clear'}
    assert block_styled('markdown', '<!-- scrub-clear: |\n  a\n-->') == {'scrub-clear'}


def test_block_styled_is_empty_without_a_block() -> None:
    assert block_styled('code', '#| scrub-clear: hello') == frozenset()
    assert block_styled('code', '#| scrub-clear: "a | b"') == frozenset()
    assert block_styled('raw', '#| scrub-clear: |') == frozenset()


def test_a_comment_eating_a_whole_value_raises() -> None:
    """'#| scrub-clear: # TODO' would otherwise fall back to the default."""
    with pytest.raises(ProcessingError, match=r"Option 'scrub-clear' is cut short"):
        options('code', '#| scrub-clear: # TODO: your code here\nprint("x")')


def test_a_comment_eating_the_end_of_a_value_raises() -> None:
    """'fill in # here' would otherwise arrive as 'fill in'."""
    with pytest.raises(ProcessingError, match=r"Option 'scrub-clear' is cut short"):
        options('code', '#| scrub-clear: fill in # here\nprint("x")')


def test_the_cut_short_message_offers_both_remedies() -> None:
    with pytest.raises(ProcessingError) as exc:
        options('code', '#| scrub-clear: # TODO\nprint("x")')
    message = str(exc.value)
    assert 'YAML comment' in message
    assert '"# TODO: your code here"' in message
    assert "'scrub-clear: |'" in message


def test_a_comment_eating_an_entry_of_a_mapping_option_raises() -> None:
    """Everything under an option's name is that option's text too."""
    source = '#| scrub-note:\n#|   id: ex-1\n#|   text: fill # here\nprint("x")'
    with pytest.raises(ProcessingError, match=r"Option 'scrub-note.text' is cut short"):
        options('code', source)


def test_a_comment_after_a_quoted_value_is_deliberate() -> None:
    """Quoting keeps the '#', so anything past the quotes is a real comment."""
    assert options('code', '#| scrub-clear: "# TODO" # aside') == {
        'scrub-clear': '# TODO',
    }


def test_a_quoted_value_keeps_its_hash_verbatim() -> None:
    assert options('code', '#| scrub-clear: "# TODO: your code here"') == {
        'scrub-clear': '# TODO: your code here',
    }


def test_a_block_scalar_keeps_its_hashes_verbatim() -> None:
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   def add(a, b):',
            '#|       # TODO: your code here',
            '#|       pass',
        ],
    )
    assert options('code', source) == {
        'scrub-clear': 'def add(a, b):\n    # TODO: your code here\n    pass',
    }


def test_a_comment_on_an_option_the_tool_does_not_define_is_left_alone() -> None:
    assert options('code', '#| fig-cap: x # note\nprint("x")') == {'fig-cap': 'x'}


def test_a_divider_comment_yields_no_options() -> None:
    assert options('code', '#|-----\nprint("x")') == {}


def test_an_unreadable_header_the_tool_does_not_own_yields_no_options() -> None:
    """The header is shared, so a neighbour's syntax is not this tool's to judge."""
    assert options('code', '#| fig-cap: A: B\nprint("x")') == {}


def test_an_unreadable_header_naming_a_scrubber_option_raises() -> None:
    with pytest.raises(ProcessingError, match='Invalid cell option header'):
        options('code', '#| scrub-clear: A: B\nprint("x")')


def test_a_non_mapping_header_the_tool_does_not_own_yields_no_options() -> None:
    assert options('code', '#| - one\n#| - two') == {}


def test_an_option_name_yaml_cannot_use_as_a_key_raises() -> None:
    """A sequence is well-formed YAML but cannot name an option."""
    with pytest.raises(ProcessingError, match='Invalid cell option header'):
        options('code', '#| ? [scrub-omit, other]\n#| : x')
