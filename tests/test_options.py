import re

from typing import Any

import pytest

from ipynb_scrubber.exceptions import ProcessingError
from ipynb_scrubber.options import Option, parse_cell_options

#: The options the tool defines, under their default spellings.
OPTIONS = (
    Option('scrub-clear', takes_text=True),
    Option('scrub-omit', takes_text=False),
    Option('scrub-note', takes_text=True),
)


def options(cell_type: str, source: str) -> dict[str, Any]:
    """The option mapping a cell's header carries."""
    return parse_cell_options(cell_type, source, OPTIONS).options


def block_styled(cell_type: str, source: str) -> frozenset[str]:
    """The names of the options a cell's header writes as a block scalar."""
    return parse_cell_options(cell_type, source, OPTIONS).block_styled


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


def test_code_option_quoted_value_expands_its_escapes() -> None:
    """A double-quoted value is YAML's escaping style, so one line carries two."""
    result = options('code', '#| scrub-clear: "line one\\nline two"\nprint("x")')
    assert result == {'scrub-clear': 'line one\nline two'}


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


def test_code_block_scalar_before_a_sibling_option_keeps_its_final_newline() -> None:
    """'|' clips: the block keeps a trailing newline only because a line follows.

    The same block written last has none, as test_code_block_scalar shows. The
    sibling below it is the neighbour's, and the block ends above it.
    """
    source = '\n'.join(
        [
            '#| scrub-clear: |',
            '#|   a',
            '#| echo: false',
            'print("x")',
        ],
    )
    result = options('code', source)
    assert result == {'scrub-clear': 'a\n', 'echo': False}


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


def test_markdown_blank_lines_around_a_comment_are_skipped() -> None:
    """A markdown cell's header survives the blank line authors write after it."""
    result = options('markdown', '\n<!-- scrub-clear: -->\n\n## Q')
    assert result == {'scrub-clear': None}


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


def test_a_bare_name_is_not_an_option() -> None:
    """An option is a mapping entry, so the colon is what names one.

    Without it the name is just a string, and the header holds no options at
    all rather than one valueless one.
    """
    with pytest.raises(ProcessingError, match=r"'scrub-omit' is missing its colon"):
        options('code', '#| scrub-omit\nprint("x")')
    with pytest.raises(ProcessingError, match=r"'scrub-omit' is missing its colon"):
        options('markdown', '<!-- scrub-omit -->\n# Solution')


def test_a_bare_name_above_prose_names_the_missing_colon() -> None:
    """A plain scalar swallows the line below it, so the value names nothing.

    'scrub-omit' above a note to self folds into one string. What the author
    wrote is still on the line the scalar opens on, which is where the missing
    colon is found.
    """
    with pytest.raises(ProcessingError, match=r"'scrub-omit' is missing its colon"):
        options('code', '#| scrub-omit\n#| the answer cell\nprint("x")')


def test_a_bare_name_is_never_silently_dropped() -> None:
    """Regression: reading one as somebody else's header ships the solution.

    A colonless name offers no colon for a key-position match to find, and it
    folds into a plain scalar that names nothing. Missing it in any of these
    shapes means scrub-omit silently does nothing and the cell survives into
    the exercise notebook.
    """
    for source in (
        '#| scrub-omit\nSECRET = 1',
        '#| scrub-omit\n#| echo: false\nSECRET = 1',
        '#| echo: false\n#| scrub-omit\nSECRET = 1',
        '#| scrub-omit\n#| the answer cell\nSECRET = 1',
    ):
        with pytest.raises(ProcessingError):
            options('code', source)


def test_a_non_text_name_beside_an_option_is_left_alone() -> None:
    """'12' is nobody's option here, so it is read as YAML reads it.

    The header carries one of this tool's options too, which does not make its
    neighbour's keys this tool's to complain about.
    """
    assert options('code', '#| scrub-clear: hello\n#| 12: hello') == {
        'scrub-clear': 'hello',
        12: 'hello',
    }


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


@pytest.mark.parametrize(
    'source',
    [
        '#| scrub-clear: A: B\nprint("x")',
        '#| fig-cap: A: B\nprint("x")',
        '#| my-scrub-omit-helper: A: B\nprint("x")',
        '#| fig-cap: see scrub-note docs: really\nprint("x")',
        '#| scrub-omit\n#| echo: false\nprint("x")',
    ],
)
def test_an_unreadable_header_always_raises(source: str) -> None:
    """Whose header it is cannot be known, so the run does not guess.

    Without a node graph there is nothing to read ownership off. Matching the
    raw text instead would claim headers that merely look like this tool's —
    a name inside a longer key, or in a neighbour's prose — and staying quiet
    would leave a cell this tool was told to scrub in the output. The header is
    YAML and Quarto reads the same block as YAML, so text this malformed is
    broken for whoever else writes here too.
    """
    with pytest.raises(ProcessingError, match='Invalid cell option header'):
        options('code', source)


def test_a_non_mapping_header_the_tool_does_not_own_yields_no_options() -> None:
    assert options('code', '#| - one\n#| - two') == {}


def test_a_non_mapping_header_is_claimed_wherever_the_name_is_written() -> None:
    """A header this shape has no keys to read ownership off, so all of it counts.

    An option written inside a list is still an option somebody wrote, and
    passing over it would leave the cell scrub-omit was meant to remove in the
    output. A list of the same shape naming nothing is somebody else's.
    """
    with pytest.raises(ProcessingError, match='must be a mapping'):
        options('code', '#| - scrub-omit: x\n#| - two')
    assert options('code', '#| - one: x\n#| - two') == {}


def test_an_option_name_yaml_cannot_use_as_a_key_raises() -> None:
    """A sequence is well-formed YAML but cannot name an option."""
    with pytest.raises(ProcessingError, match='Invalid cell option header'):
        options('code', '#| ? [scrub-omit, other]\n#| : x')


@pytest.mark.parametrize(
    'source',
    [
        '#| ? [a, b]\n#| : c',
        '#| foo: !!weird bar',
    ],
)
def test_a_header_yaml_parses_but_cannot_build_raises(source: str) -> None:
    """Regression: these named no option, so ownership used to swallow them.

    YAML gives up on some headers only once it starts turning the parsed text
    into values — a key nothing can hash, a tag nothing can build. That is a
    malformed header like any other, and it is reported whether or not it
    names one of this tool's options.
    """
    with pytest.raises(ProcessingError, match='Invalid cell option header'):
        options('code', source)


def test_a_non_text_name_the_tool_does_not_own_is_left_alone() -> None:
    """The header names no scrubber option, so its keys are not this tool's."""
    assert options('code', '#| 12: hello') == {12: 'hello'}


def test_a_repeated_name_the_tool_does_not_own_is_left_alone() -> None:
    """Whether a neighbour may repeat its own option is not this tool's call.

    YAML keeps the last of the two, and that is what the header yields: this
    tool never reads a name it does not define, so it has nothing to lose to
    the repeat and nothing to say about it.
    """
    assert options('code', '#| fig-cap: a\n#| fig-cap: b\nprint("x")') == {
        'fig-cap': 'b',
    }


def test_a_repeated_foreign_name_beside_an_option_is_left_alone() -> None:
    """Regression: owning one key in a header did not make its neighbours ours.

    Ownership is decided per entry, so a repeat under somebody else's name does
    not turn into a refusal to scrub the cell just because this tool also has
    an option in the same header.
    """
    source = '#| scrub-clear: hi\n#| fig-cap: a\n#| fig-cap: b\nprint("x")'
    assert options('code', source) == {'scrub-clear': 'hi', 'fig-cap': 'b'}


def test_a_repeat_under_a_foreign_name_beside_an_option_is_left_alone() -> None:
    """Everything under a neighbour's name is the neighbour's, nesting and all."""
    source = '#| scrub-clear: hi\n#| opts:\n#|   a: 1\n#|   a: 2\nprint("x")'
    assert options('code', source) == {'scrub-clear': 'hi', 'opts': {'a': 2}}


def test_a_repeated_option_beside_a_foreign_name_still_raises() -> None:
    """A repeat of this tool's own name loses an instruction it was given."""
    source = '#| fig-cap: a\n#| scrub-clear: first\n#| scrub-clear: second'
    with pytest.raises(ProcessingError, match=r"Duplicate option 'scrub-clear'"):
        options('code', source)


def test_a_comment_eating_a_foreign_value_beside_an_option_is_left_alone() -> None:
    """A neighbour's quoting is the neighbour's business, header shared or not."""
    source = '#| scrub-clear: hi\n#| fig-cap: x # note\nprint("x")'
    assert options('code', source) == {'scrub-clear': 'hi', 'fig-cap': 'x'}


def test_a_longer_name_containing_a_scrubber_name_is_not_owned() -> None:
    """'my-scrub-omit-helper' is somebody else's option, not scrub-omit.

    Ownership comes off the parsed keys, so a name is claimed only where one
    was written and not merely where the characters appear.
    """
    assert options('code', '#| my-scrub-omit-helper: false\nprint("x")') == {
        'my-scrub-omit-helper': False,
    }


def test_a_scrubber_name_inside_a_foreign_value_is_not_owned() -> None:
    """A key names an option; a name in somebody else's value does not."""
    assert options('code', '#| fig-cap: see scrub-note docs\nprint("x")') == {
        'fig-cap': 'see scrub-note docs',
    }


def test_a_repeated_entry_in_a_mapping_option_raises() -> None:
    """Everything under an option's name is that option's instruction too."""
    source = '#| scrub-note:\n#|   id: a\n#|   id: b\nprint("x")'
    with pytest.raises(ProcessingError, match=r"Duplicate option 'scrub-note.id'"):
        options('code', source)


def test_a_comment_beside_an_option_that_takes_no_value_is_left_alone() -> None:
    """scrub-omit carries no value, so a comment cannot cut one short."""
    assert options('code', '#| scrub-omit: # drop the answer\nprint("x")') == {
        'scrub-omit': None,
    }


def test_an_unquoted_colon_in_a_value_names_the_quoting_fix() -> None:
    """A caption carrying a colon is the likeliest way a header stops parsing.

    YAML's own words for it name the mechanism, not the remedy. Quarto reads
    the same header under the same rules and tells authors to quote the value,
    so this does too.
    """
    with pytest.raises(ProcessingError, match=r"has a second ':' in its value"):
        options('code', '#| fig-cap: Figure 1: Temperature\nprint("x")')
