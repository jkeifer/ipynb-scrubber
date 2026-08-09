import pytest

from ipynb_scrubber.actions import Clear, Keep, Note, Omit, apply, decide
from ipynb_scrubber.config import ScrubbingOptions
from ipynb_scrubber.exceptions import ProcessingError

OPTS = ScrubbingOptions()


def cell(source: str, cell_type: str = 'code', **metadata) -> dict:
    return {'cell_type': cell_type, 'source': source, 'metadata': metadata}


def test_plain_cell_is_kept():
    assert decide(cell('x = 1'), OPTS) == Keep()


def test_omit_via_source_option():
    assert decide(cell('#| scrub-omit\nx = 1'), OPTS) == Omit()


def test_omit_via_tag():
    assert decide(cell('x = 1', tags=['scrub-omit']), OPTS) == Omit()


def test_clear_uses_configured_default_when_bare():
    assert decide(cell('#| scrub-clear\nx = 1'), OPTS) == Clear(OPTS.clear_text)


def test_clear_uses_inline_text():
    assert decide(cell('#| scrub-clear: do it\nx = 1'), OPTS) == Clear('do it')


def test_clear_empty_value_is_not_the_default():
    assert decide(cell('#| scrub-clear:\nx = 1'), OPTS) == Clear('')


def test_note_defaults_to_clear_text():
    assert decide(cell('#| scrub-note: ex-1\nx = 1'), OPTS) == Note(
        'ex-1',
        OPTS.clear_text,
    )


def test_note_with_escaped_pipe_in_id():
    assert decide(cell(r'#| scrub-note: a\|b' + '\nx = 1'), OPTS) == Note(
        'a|b',
        OPTS.clear_text,
    )


def test_omit_tag_beats_note_tag():
    """Both as metadata tags: omit wins, no error. Documented in the README."""
    assert decide(cell('x = 1', tags=['scrub-omit', 'scrub-note']), OPTS) == Omit()


def test_multiple_scrubber_options_in_one_header_error():
    """No block is present, so the block-indentation hint would be nonsense.

    '#| scrub-omit' + '#| scrub-note: ex-1' has no block opener anywhere, so
    suggesting the reader re-indent a block is wrong advice; the hint must
    not be appended.
    """
    with pytest.raises(ProcessingError, match=r'only one .* option per cell') as exc:
        decide(cell('#| scrub-omit\n#| scrub-note: ex-1\nx = 1'), OPTS)
    assert 'indent it more deeply' not in str(exc.value)


def test_multiple_scrubber_options_catches_underindented_block_content():
    """The F5 hazard: block content that lost its indentation.

    '#| scrub-omit' here is indistinguishable from a sibling option at the
    syntax level, and reading it as one would silently delete the cell. A
    block is present, so the indentation hint is relevant and must be
    appended.
    """
    with pytest.raises(ProcessingError, match=r'only one .* option per cell') as exc:
        decide(cell('#| scrub-clear: |\n#| scrub-omit\nSECRET = 1'), OPTS)
    assert 'indent it more deeply' in str(exc.value)


def test_non_scrubber_sibling_options_are_allowed():
    """A Quarto option after an empty block opener must stay legal."""
    assert decide(cell('#| scrub-note: ex-1 |\n#| echo: false\nx = 1'), OPTS) == Note(
        'ex-1',
        '',
    )


def test_tag_omit_plus_source_note_is_allowed():
    """One source option, so the documented tag-level precedence still holds."""
    assert (
        decide(cell('#| scrub-note: ex-1\nx = 1', tags=['scrub-omit']), OPTS) == Omit()
    )


def test_note_as_tag_errors():
    with pytest.raises(ProcessingError, match='not supported as a cell tag'):
        decide(cell('x = 1', tags=['scrub-note']), OPTS)


def test_note_on_markdown_errors():
    with pytest.raises(ProcessingError, match='only supported on code cells'):
        decide(cell('<!-- scrub-note: ex-1 -->', cell_type='markdown'), OPTS)


@pytest.mark.parametrize(
    'source',
    ['#| scrub-note', '#| scrub-note:', '#| scrub-note: | text'],
)
def test_note_without_id_errors(source):
    with pytest.raises(ProcessingError, match='requires an id'):
        decide(cell(f'{source}\nx = 1'), OPTS)


def test_apply_strips_outputs_and_execution_count():
    target = {
        'cell_type': 'code',
        'source': 'x = 1',
        'outputs': [1],
        'execution_count': 3,
    }
    result = apply(target, Keep())
    assert 'outputs' not in result
    assert 'execution_count' not in result
    assert result['source'] == 'x = 1'


def test_apply_leaves_the_input_cell_alone():
    """apply builds a new cell, so a later failure cannot half-scrub the input."""
    target = {
        'cell_type': 'code',
        'source': 'x = 1',
        'outputs': [1],
        'execution_count': 3,
    }
    original = dict(target)

    result = apply(target, Clear('replaced'))

    assert target == original
    assert result is not target
    assert result['source'] == 'replaced'


def test_apply_note_writes_reference_comment():
    result = apply({'cell_type': 'code', 'source': 'x = 1'}, Note('ex-1', '# TODO'))
    assert result['source'] == '# (See notes: ex-1)\n# TODO'


def test_apply_note_with_empty_text_omits_the_newline():
    result = apply({'cell_type': 'code', 'source': 'x = 1'}, Note('ex-1', ''))
    assert result['source'] == '# (See notes: ex-1)'


def test_note_inline_text_and_block_conflict_errors():
    """Wording matches Option.single_text's conflict message (options.py):

    the same mistake on scrub-clear vs scrub-note must get the same advice,
    including the '\\|' escape hint.
    """
    with pytest.raises(
        ProcessingError,
        match=r"has both inline text and a block.*escape a literal pipe as '\\\|'",
    ):
        decide(
            cell('#| scrub-note: ex-1 | inline text |\n#|   more\nx = 1'),
            OPTS,
        )


def test_note_uses_inline_replacement_text():
    assert decide(cell('#| scrub-note: ex-1 | inline text\nx = 1'), OPTS) == Note(
        'ex-1',
        'inline text',
    )


def test_clear_via_tag_only():
    assert decide(cell('x = 1', tags=['scrub-clear']), OPTS) == Clear(OPTS.clear_text)


def test_apply_clear_replaces_source():
    result = apply({'cell_type': 'code', 'source': 'x = 1'}, Clear('replaced'))
    assert result['source'] == 'replaced'
