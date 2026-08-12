import pytest

from ipynb_scrubber.actions import (
    _CLEAR_TEXT_FIELDS,
    MARKERS,
    Clear,
    Keep,
    Note,
    Omit,
    Scrubber,
    ScrubbingOptions,
)
from ipynb_scrubber.exceptions import ProcessingError, ScrubberError
from ipynb_scrubber.notebook import CELL_TYPES, get_cell_source
from tests.builders import code, markdown, raw

OPTS = ScrubbingOptions()
SCRUBBER = Scrubber(OPTS)


def test_plain_cell_is_kept():
    assert SCRUBBER.decide(code('x = 1')) == Keep()


def test_omit_via_source_option():
    assert SCRUBBER.decide(code('#| scrub-omit:\nx = 1')) == Omit()


def test_omit_via_tag():
    assert SCRUBBER.decide(code('x = 1', tags=['scrub-omit'])) == Omit()


def test_omit_with_a_value_errors():
    """Presence is the whole signal, so a value means the author meant something."""
    with pytest.raises(ProcessingError, match='takes no value'):
        SCRUBBER.decide(code('#| scrub-omit: true\nx = 1'))


def test_clear_uses_configured_default_when_valueless():
    assert SCRUBBER.decide(code('#| scrub-clear:\nx = 1')) == Clear(OPTS.clear_text)


def test_clear_uses_inline_text():
    assert SCRUBBER.decide(code('#| scrub-clear: do it\nx = 1')) == Clear('do it')


def test_clear_empty_string_is_not_the_default():
    assert SCRUBBER.decide(code('#| scrub-clear: ""\nx = 1')) == Clear('')


def test_clear_uses_a_block_scalar_for_multiple_lines():
    source = '#| scrub-clear: |\n#|   def add(a, b):\n#|       pass\nx = 1'
    assert SCRUBBER.decide(code(source)) == Clear('def add(a, b):\n    pass')


def test_clear_rejects_a_value_that_is_not_text():
    """'no' is a YAML boolean, and clearing a cell to 'False' is never meant."""
    with pytest.raises(ProcessingError, match='takes replacement text'):
        SCRUBBER.decide(code('#| scrub-clear: no\nx = 1'))


def test_note_defaults_to_clear_text():
    assert SCRUBBER.decide(code('#| scrub-note: ex-1\nx = 1')) == Note(
        'ex-1',
        OPTS.clear_text,
        'x = 1',
    )


def test_omit_tag_beats_note_tag():
    """Both as metadata tags: omit wins, no error. Documented in the README."""
    assert SCRUBBER.decide(code('x = 1', tags=['scrub-omit', 'scrub-note'])) == Omit()


def test_omit_tag_beats_clear_tag():
    """Dropping a cell subsumes rewriting it, so omit is considered first."""
    assert SCRUBBER.decide(code('x = 1', tags=['scrub-omit', 'scrub-clear'])) == Omit()


def test_markers_are_considered_omit_then_note_then_clear():
    """The registry's order is the precedence order, so it is load-bearing.

    Omit first because dropping a cell subsumes every rewrite of it, and note
    before clear because a note is a clear that also files away what it
    removed. Reordering the table silently changes what a cell carrying two
    markers becomes.
    """
    assert [option.key for option in MARKERS] == ['omit-tag', 'note-tag', 'clear-tag']


def test_multiple_scrubber_options_in_one_header_error():
    """No block is present, so the block-indentation hint would be nonsense.

    '#| scrub-omit:' + '#| scrub-note: ex-1' has no block opener anywhere, so
    suggesting the reader re-indent a block is wrong advice; the hint must
    not be appended.
    """
    with pytest.raises(ProcessingError, match=r'only one .* option per cell') as exc:
        SCRUBBER.decide(code('#| scrub-omit:\n#| scrub-note: ex-1\nx = 1'))
    assert 'indent it more deeply' not in str(exc.value)


def test_multiple_scrubber_options_catches_underindented_block_content():
    """The F5 hazard: block content that lost its indentation.

    '#| scrub-omit:' here is an empty block scalar plus a sibling option, and
    reading it that way would silently delete the cell. A block is present, so
    the indentation hint is relevant and must be appended.
    """
    with pytest.raises(ProcessingError, match=r'only one .* option per cell') as exc:
        SCRUBBER.decide(code('#| scrub-clear: |\n#| scrub-omit:\nSECRET = 1'))
    assert 'indent it more deeply' in str(exc.value)


def test_non_scrubber_sibling_options_are_allowed():
    """A Quarto option alongside a scrubber option must stay legal, and survive.

    '#| echo: false' configures the cell that remains in the exercise notebook,
    so removing it along with the scrub-note that sat above it would silently
    change how the notebook renders.
    """
    assert SCRUBBER.decide(code('#| scrub-note: ex-1\n#| echo: false\nx = 1')) == Note(
        'ex-1',
        OPTS.clear_text,
        'x = 1',
        '#| echo: false',
    )


def test_sibling_options_are_kept_in_the_order_they_were_written():
    """Kept lines come back in source order, from both sides of the option.

    They are all written back above the replacement whatever their original
    order, since a '#|' run only reads as options at the very top of a cell.
    """
    source = '#| echo: false\n#| scrub-clear: fill me in\n#| fig-cap: A plot\nX = 1'
    assert SCRUBBER.decide(code(source)) == Clear(
        'fill me in',
        '#| echo: false\n#| fig-cap: A plot',
    )


def test_decide_reads_a_list_source_as_one_string():
    """Jupyter's native on-disk format stores source as a list of lines.

    The header spans several of them, and the body a note captures is what is
    left once they are joined back together.
    """
    cell = code(['#| scrub-note: ex-1\n', 'line one\n', 'line two'])
    assert SCRUBBER.decide(cell) == Note('ex-1', OPTS.clear_text, 'line one\nline two')


def test_tag_omit_plus_source_note_is_allowed():
    """One source option, so the documented tag-level precedence still holds."""
    cell = code('#| scrub-note: ex-1\nx = 1', tags=['scrub-omit'])
    assert SCRUBBER.decide(cell) == Omit()


def test_source_omit_plus_tag_clear_is_allowed():
    """The mirror of the above: precedence is the marker's, not the spelling's.

    Whichever way round the two names are written, the earlier marker wins, so
    neither source of names is privileged over the other.
    """
    cell = code('#| scrub-omit:\nx = 1', tags=['scrub-clear'])
    assert SCRUBBER.decide(cell) == Omit()


def test_a_headers_value_beats_the_same_name_as_a_tag():
    """One name, written both ways: only the header can carry a value at all.

    A tag says nothing but 'present', so letting it answer for a name the
    header spells out would throw the author's replacement text away.
    """
    cell = code('#| scrub-clear: from the header\nx = 1', tags=['scrub-clear'])
    assert SCRUBBER.decide(cell) == Clear('from the header')


@pytest.mark.parametrize('builder', [code, markdown, raw])
def test_note_as_tag_errors(builder):
    """A tag carries no id, whatever kind of cell it is written on."""
    with pytest.raises(ProcessingError, match='not supported as a cell tag'):
        SCRUBBER.decide(builder('x = 1', tags=['scrub-note']))


def test_note_as_tag_errors_under_its_configured_spelling():
    """The refusal names the tag the run reads, not the default one."""
    scrubber = Scrubber(ScrubbingOptions(note_tag='keepme'))
    with pytest.raises(
        ProcessingError,
        match="Option 'keepme' is not supported as a cell tag",
    ):
        scrubber.decide(code('x = 1', tags=['keepme']))


def test_note_on_markdown_errors():
    with pytest.raises(ProcessingError, match='only supported on code cells'):
        SCRUBBER.decide(markdown('<!-- scrub-note: ex-1 -->'))


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
        SCRUBBER.decide(code(f'{source}\nx = 1'))


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
    assert SCRUBBER.decide(code(source)) == Note(
        'ex-1',
        'def add(a, b):\n    pass',
        'x = 1',
    )


def test_note_mapping_without_text_uses_the_default():
    source = '#| scrub-note:\n#|   id: ex-1\nx = 1'
    assert SCRUBBER.decide(code(source)) == Note('ex-1', OPTS.clear_text, 'x = 1')


def test_note_mapping_rejects_an_unknown_key():
    source = '#| scrub-note:\n#|   id: ex-1\n#|   txet: oops\nx = 1'
    with pytest.raises(ScrubberError, match='Unknown scrub-note key'):
        SCRUBBER.decide(code(source))


def test_note_mapping_rejects_text_that_is_not_a_string():
    source = '#| scrub-note:\n#|   id: ex-1\n#|   text: 3.5\nx = 1'
    with pytest.raises(ProcessingError, match='takes replacement text'):
        SCRUBBER.decide(code(source))


def test_apply_empties_a_code_cells_outputs_and_execution_count():
    """Emptied, not removed: nbformat requires both keys on every code cell."""
    target = {
        'cell_type': 'code',
        'source': 'x = 1',
        'outputs': [1],
        'execution_count': 3,
    }
    result = SCRUBBER.apply(target, Keep())
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
    result = SCRUBBER.apply(target, Keep())
    assert 'outputs' not in result
    assert 'execution_count' not in result


def test_apply_keeps_a_list_source_a_list():
    """A rewritten cell keeps the source shape it arrived in, as Jupyter writes it."""
    target = {'cell_type': 'code', 'source': ['x = 1\n', 'y = 2'], 'metadata': {}}
    assert SCRUBBER.apply(target, Clear('a\nb'))['source'] == ['a\n', 'b']


def test_apply_keeps_a_string_source_a_string():
    target = {'cell_type': 'code', 'source': 'x = 1', 'metadata': {}}
    assert SCRUBBER.apply(target, Clear('a\nb'))['source'] == 'a\nb'


def test_apply_leaves_the_input_cell_alone():
    """apply builds a new cell, so a later failure cannot half-scrub the input."""
    target = {
        'cell_type': 'code',
        'source': 'x = 1',
        'outputs': [1],
        'execution_count': 3,
    }
    original = dict(target)

    result = SCRUBBER.apply(target, Clear('replaced'))

    assert target == original
    assert result is not target
    assert result['source'] == 'replaced'


def test_apply_note_writes_reference_comment():
    result = SCRUBBER.apply(
        {'cell_type': 'code', 'source': 'x = 1'},
        Note('ex-1', '# TODO', ''),
    )
    assert result['source'] == '# (See notes: ex-1)\n# TODO'


def test_apply_note_with_empty_text_omits_the_newline():
    cell = {'cell_type': 'code', 'source': 'x = 1'}
    result = SCRUBBER.apply(cell, Note('ex-1', '', ''))
    assert result['source'] == '# (See notes: ex-1)'


def test_apply_note_uses_the_configured_reference():
    """A kernel whose comment syntax is not '#' needs its own marker."""
    scrubber = Scrubber(
        ScrubbingOptions(note_reference='// (See notes: {id})'),
    )
    cell = {'cell_type': 'code', 'source': 'x = 1'}
    result = scrubber.apply(cell, Note('ex-1', '', ''))
    assert result['source'] == '// (See notes: ex-1)'


def test_apply_note_reference_substitutes_only_the_id():
    """A literal brace is text, not a field: str.format would raise on it."""
    scrubber = Scrubber(
        ScrubbingOptions(note_reference='# {see} (See notes: {id})'),
    )
    cell = {'cell_type': 'code', 'source': 'x = 1'}
    result = scrubber.apply(cell, Note('ex-1', '', ''))
    assert result['source'] == '# {see} (See notes: ex-1)'


def test_clear_via_tag_only():
    cell = code('x = 1', tags=['scrub-clear'])
    assert SCRUBBER.decide(cell) == Clear(OPTS.clear_text)


@pytest.mark.parametrize(
    ('builder', 'expected'),
    [
        (code, '# TODO: Implement this'),
        (markdown, '*TODO: Implement this*'),
        (raw, 'TODO: Implement this'),
    ],
)
def test_clear_defaults_to_the_text_written_for_the_cells_own_type(builder, expected):
    """Each cell type reads its own markup, so each gets its own placeholder.

    The text is spelled out rather than looked up, since an expectation read
    back out of the code under test agrees with it however wrong it is.
    """
    cell = builder('secret', tags=['scrub-clear'])
    assert SCRUBBER.decide(cell) == Clear(expected)


@pytest.mark.parametrize(
    ('builder', 'expected'),
    [
        (code, 'write code'),
        (markdown, 'write prose'),
        (raw, 'write text'),
    ],
)
def test_clear_defaults_to_the_text_the_run_configured_for_that_type(
    builder,
    expected,
):
    """The default comes from the option naming that cell type, not a constant."""
    scrubber = Scrubber(
        ScrubbingOptions(
            clear_text='write code',
            clear_text_markdown='write prose',
            clear_text_raw='write text',
        ),
    )
    assert scrubber.decide(builder('secret', tags=['scrub-clear'])) == Clear(expected)


def test_every_cell_type_has_its_own_clear_text():
    """The lookup is total over the cell types, so it needs no default.

    Clearing indexes by cell type with nothing to fall back on, which is only
    safe while the two agree. A type validation lets through but this table
    does not name would be a KeyError on a notebook the tool accepted.
    """
    assert set(_CLEAR_TEXT_FIELDS) == set(CELL_TYPES)


def test_apply_strips_the_scrubber_tag_a_cell_was_marked_with():
    """A tag is an instruction to this tool, so it goes out with the answer.

    The source-header spelling is taken back out of the cell it marked; leaving
    the metadata spelling behind would point at the cells holding the answers.
    """
    target = code('x = 1', tags=['scrub-clear'])
    assert 'tags' not in SCRUBBER.apply(target, Clear('replaced')).get('metadata', {})


def test_apply_keeps_metadata_tags_that_are_not_this_tools():
    """The tag list is shared; only this tool's own tags are this tool's to take."""
    target = code('x = 1', tags=['hide-input', 'scrub-clear'])
    result = SCRUBBER.apply(target, Clear('replaced'))
    assert result['metadata']['tags'] == ['hide-input']


def test_apply_strips_the_scrubber_tag_under_its_configured_spelling():
    """The tag to remove is the one the run reads, not the default one."""
    scrubber = Scrubber(ScrubbingOptions(clear_tag='solution'))
    target = code('x = 1', tags=['solution', 'scrub-clear'])
    result = scrubber.apply(target, Clear('replaced'))
    assert result['metadata']['tags'] == ['scrub-clear']


def test_apply_leaves_the_input_cells_tags_alone():
    """The copy is shallow, so the tag list has to be rebuilt rather than edited."""
    target = code('x = 1', tags=['scrub-clear'])

    SCRUBBER.apply(target, Clear('replaced'))

    assert target['metadata']['tags'] == ['scrub-clear']


def test_apply_clear_replaces_source():
    result = SCRUBBER.apply({'cell_type': 'code', 'source': 'x = 1'}, Clear('replaced'))
    assert result['source'] == 'replaced'


def test_apply_writes_a_kept_header_above_the_replacement():
    """'#| echo: false' configures the cell that remains, so it remains too."""
    result = SCRUBBER.apply(
        {'cell_type': 'code', 'source': 'x = 1'},
        Clear('fill me in', '#| echo: false'),
    )
    assert result['source'] == '#| echo: false\nfill me in'


def test_apply_writes_a_kept_header_above_a_notes_reference():
    result = SCRUBBER.apply(
        {'cell_type': 'code', 'source': 'x = 1'},
        Note('ex-1', '# TODO', '', '#| echo: false'),
    )
    assert result['source'] == '#| echo: false\n# (See notes: ex-1)\n# TODO'


#: The options that mark cells, taken from the table rather than listed again:
#: an option added there is exercised below without anyone remembering to.
MARKER_CASES = [pytest.param(option, id=option.key) for option in MARKERS]


def answer_for(scrubber, cell):
    """What a run has to say about ``cell``: the source it ships with, ``''``
    if it is dropped, or the refusal raised in place of an action.

    A refusal is an answer -- the run stops and nothing is written -- so the
    three are one return type here. A cell that comes back carrying its own
    source is the one case where nobody said anything about it.
    """
    try:
        action = scrubber.decide(cell)
    except ProcessingError as refusal:
        return str(refusal)

    if isinstance(action, Omit):
        return ''

    return get_cell_source(scrubber.apply(cell, action))


@pytest.mark.parametrize('option', MARKER_CASES)
def test_a_configured_header_option_scrubs_the_cell_it_marks(option):
    """Every marker in the table reaches the cell, under the run's own spelling.

    The name configured here is nobody's default, so a layer that hardcoded a
    default, or that never heard of this option at all, decides Keep and ships
    SECRET in the exercise notebook. ``takes_text`` is the table's own word for
    "this option's value is text"; the rest carry presence and reject a value.
    """
    name = f'renamed-{option.key}'
    scrubber = Scrubber(ScrubbingOptions(**{option.field: name}))
    value = ' replaced' if option.takes_text else ''

    answer = answer_for(scrubber, code(f'#| {name}:{value}\nSECRET = 1'))

    assert 'SECRET' not in answer


@pytest.mark.parametrize('option', MARKER_CASES)
def test_a_configured_metadata_tag_is_never_silently_ignored(option):
    """The same markers, spelled as metadata tags rather than header options.

    A tag carries a name and nothing else, which is not enough for every
    option: the note option needs an id, so as a tag it is refused outright
    rather than acted on. Refusing is not ignoring, and this test asks only
    that the tag be noticed -- what the refusal says is
    test_note_as_tag_errors' business, and what a clear or an omit does is the
    business of the tests above.
    """
    name = f'renamed-{option.key}'
    scrubber = Scrubber(ScrubbingOptions(**{option.field: name}))

    answer = answer_for(scrubber, code('SECRET = 1', tags=[name]))

    assert 'SECRET' not in answer


@pytest.mark.parametrize('option', MARKER_CASES)
def test_a_default_spelling_is_inert_once_the_option_is_renamed(option):
    """Renaming an option moves it: the name it used to answer to is nobody's.

    A run reads the spelling it was configured with and no other, so a header
    or a tag left under the default name is somebody else's option now. Acting
    on it anyway would scrub a cell nothing in this run marked.
    """
    default = getattr(OPTS, option.field)
    scrubber = Scrubber(
        ScrubbingOptions(**{option.field: f'renamed-{option.key}'}),
    )
    value = ' replaced' if option.takes_text else ''

    assert 'SECRET' in answer_for(scrubber, code(f'#| {default}:{value}\nSECRET = 1'))
    assert 'SECRET' in answer_for(scrubber, code('SECRET = 1', tags=[default]))
