import pytest

from ipynb_scrubber.actions import Clear, Keep, Note, Omit, apply, decide
from ipynb_scrubber.config import ScrubbingOptions
from ipynb_scrubber.exceptions import ProcessingError
from tests.builders import cell

OPTS = ScrubbingOptions()


def test_plain_cell_is_kept():
    assert decide(cell('x = 1'), OPTS) == Keep()


def test_omit_via_source_option():
    assert decide(cell('#| scrub-omit:\nx = 1'), OPTS) == Omit()


def test_omit_via_tag():
    assert decide(cell('x = 1', tags=['scrub-omit']), OPTS) == Omit()


def test_omit_with_a_value_errors():
    """Presence is the whole signal, so a value means the author meant something."""
    with pytest.raises(ProcessingError, match='takes no value'):
        decide(cell('#| scrub-omit: true\nx = 1'), OPTS)


def test_clear_uses_configured_default_when_valueless():
    assert decide(cell('#| scrub-clear:\nx = 1'), OPTS) == Clear(OPTS.clear_text)


def test_clear_uses_inline_text():
    assert decide(cell('#| scrub-clear: do it\nx = 1'), OPTS) == Clear('do it')


def test_clear_empty_string_is_not_the_default():
    assert decide(cell('#| scrub-clear: ""\nx = 1'), OPTS) == Clear('')


def test_clear_uses_a_block_scalar_for_multiple_lines():
    source = '#| scrub-clear: |\n#|   def add(a, b):\n#|       pass\nx = 1'
    assert decide(cell(source), OPTS) == Clear('def add(a, b):\n    pass')


def test_clear_rejects_a_value_that_is_not_text():
    """'no' is a YAML boolean, and clearing a cell to 'False' is never meant."""
    with pytest.raises(ProcessingError, match='takes replacement text'):
        decide(cell('#| scrub-clear: no\nx = 1'), OPTS)


def test_note_defaults_to_clear_text():
    assert decide(cell('#| scrub-note: ex-1\nx = 1'), OPTS) == Note(
        'ex-1',
        OPTS.clear_text,
        'x = 1',
    )


def test_omit_tag_beats_note_tag():
    """Both as metadata tags: omit wins, no error. Documented in the README."""
    assert decide(cell('x = 1', tags=['scrub-omit', 'scrub-note']), OPTS) == Omit()


def test_multiple_scrubber_options_in_one_header_error():
    """No block is present, so the block-indentation hint would be nonsense.

    '#| scrub-omit:' + '#| scrub-note: ex-1' has no block opener anywhere, so
    suggesting the reader re-indent a block is wrong advice; the hint must
    not be appended.
    """
    with pytest.raises(ProcessingError, match=r'only one .* option per cell') as exc:
        decide(cell('#| scrub-omit:\n#| scrub-note: ex-1\nx = 1'), OPTS)
    assert 'indent it more deeply' not in str(exc.value)


def test_multiple_scrubber_options_catches_underindented_block_content():
    """The F5 hazard: block content that lost its indentation.

    '#| scrub-omit:' here is an empty block scalar plus a sibling option, and
    reading it that way would silently delete the cell. A block is present, so
    the indentation hint is relevant and must be appended.
    """
    with pytest.raises(ProcessingError, match=r'only one .* option per cell') as exc:
        decide(cell('#| scrub-clear: |\n#| scrub-omit:\nSECRET = 1'), OPTS)
    assert 'indent it more deeply' in str(exc.value)


def test_non_scrubber_sibling_options_are_allowed():
    """A Quarto option alongside a scrubber option must stay legal, and survive.

    '#| echo: false' configures the cell that remains in the exercise notebook,
    so removing it along with the scrub-note that sat above it would silently
    change how the notebook renders.
    """
    assert decide(cell('#| scrub-note: ex-1\n#| echo: false\nx = 1'), OPTS) == Note(
        'ex-1',
        OPTS.clear_text,
        'x = 1',
        '#| echo: false',
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
    [
        '#| scrub-note:',
        '#| scrub-note: ""',
        '#| scrub-note: 12',
        '#| scrub-note:\n#|   id:',
        '#| scrub-note:\n#|   text: hello',
    ],
)
def test_note_without_id_errors(source):
    with pytest.raises(ProcessingError, match='requires an id'):
        decide(cell(f'{source}\nx = 1'), OPTS)


def test_note_mapping_supplies_replacement_text():
    source = '\n'.join(
        [
            '#| scrub-note:',
            '#|   id: ex-1',
            '#|   text: |',
            '#|     def add(a, b):',
            '#|         pass',
            'x = 1',
        ],
    )
    assert decide(cell(source), OPTS) == Note(
        'ex-1',
        'def add(a, b):\n    pass',
        'x = 1',
    )


def test_note_mapping_without_text_uses_the_default():
    source = '#| scrub-note:\n#|   id: ex-1\nx = 1'
    assert decide(cell(source), OPTS) == Note('ex-1', OPTS.clear_text, 'x = 1')


def test_note_mapping_rejects_an_unknown_key():
    source = '#| scrub-note:\n#|   id: ex-1\n#|   txet: oops\nx = 1'
    with pytest.raises(ProcessingError, match='Unknown scrub-note key'):
        decide(cell(source), OPTS)


def test_note_mapping_rejects_text_that_is_not_a_string():
    source = '#| scrub-note:\n#|   id: ex-1\n#|   text: 3.5\nx = 1'
    with pytest.raises(ProcessingError, match='takes replacement text'):
        decide(cell(source), OPTS)


def test_apply_empties_a_code_cells_outputs_and_execution_count():
    """Emptied, not removed: nbformat requires both keys on every code cell."""
    target = {
        'cell_type': 'code',
        'source': 'x = 1',
        'outputs': [1],
        'execution_count': 3,
    }
    result = apply(target, Keep())
    assert result['outputs'] == []
    assert result['execution_count'] is None
    assert result['source'] == 'x = 1'


@pytest.mark.parametrize('cell_type', ['markdown', 'raw'])
def test_apply_removes_run_results_from_a_non_code_cell(cell_type):
    """Only a code cell may carry them, so elsewhere they are dropped outright."""
    target = {
        'cell_type': cell_type,
        'source': 'text',
        'outputs': [1],
        'execution_count': 3,
    }
    result = apply(target, Keep())
    assert 'outputs' not in result
    assert 'execution_count' not in result


def test_apply_keeps_a_list_source_a_list():
    """A rewritten cell keeps the source shape it arrived in, as Jupyter writes it."""
    target = {'cell_type': 'code', 'source': ['x = 1\n', 'y = 2'], 'metadata': {}}
    assert apply(target, Clear('a\nb'))['source'] == ['a\n', 'b']


def test_apply_keeps_a_string_source_a_string():
    target = {'cell_type': 'code', 'source': 'x = 1', 'metadata': {}}
    assert apply(target, Clear('a\nb'))['source'] == 'a\nb'


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
    result = apply({'cell_type': 'code', 'source': 'x = 1'}, Note('ex-1', '# TODO', ''))
    assert result['source'] == '# (See notes: ex-1)\n# TODO'


def test_apply_note_with_empty_text_omits_the_newline():
    result = apply({'cell_type': 'code', 'source': 'x = 1'}, Note('ex-1', '', ''))
    assert result['source'] == '# (See notes: ex-1)'


def test_clear_via_tag_only():
    assert decide(cell('x = 1', tags=['scrub-clear']), OPTS) == Clear(OPTS.clear_text)


def test_apply_clear_replaces_source():
    result = apply({'cell_type': 'code', 'source': 'x = 1'}, Clear('replaced'))
    assert result['source'] == 'replaced'
