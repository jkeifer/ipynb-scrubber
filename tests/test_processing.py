import copy

import pytest

from ipynb_scrubber.config import ScrubbingOptions
from ipynb_scrubber.exceptions import InvalidNotebookError, ProcessingError
from ipynb_scrubber.notebook import get_notebook_language
from ipynb_scrubber.notes import write_notes_file
from ipynb_scrubber.processor import process_notebook

OPTS = ScrubbingOptions()


def notebook(*sources: tuple[str, str]):
    return {
        'cells': [
            {'cell_type': ct, 'source': src, 'metadata': {}} for ct, src in sources
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }


def test_duplicate_note_ids_error():
    nb = notebook(
        ('code', '#| scrub-note: ex-1\nSOLUTION_A = 1'),
        ('code', '#| scrub-note: ex-1\nSOLUTION_B = 2'),
    )
    with pytest.raises(
        ProcessingError,
        match=r"Cell 1.*[Dd]uplicate note id 'ex-1'",
    ) as exc_info:
        process_notebook(nb, OPTS)
    message = str(exc_info.value)
    assert 'cell 0' in message
    assert 'Cell 1' in message


def test_error_is_prefixed_with_the_offending_cell_index():
    nb = notebook(
        ('code', 'a = 1'),
        ('code', 'b = 2'),
        ('code', 'c = 3'),
        ('markdown', '<!-- scrub-note: x -->'),
    )
    with pytest.raises(ProcessingError, match=r'^Cell 3: '):
        process_notebook(nb, OPTS)


def test_internal_bug_surfaces_as_a_bug_not_a_processing_error(
    monkeypatch,
    make_notebook,
    code,
):
    """Only ScrubberError carries the friendly, traceback-free contract.

    Anything else escaping cell processing is a defect in this tool, and
    wrapping it in ProcessingError would present it to the user as though
    their notebook were at fault.
    """

    def boom(*_args, **_kwargs):
        raise RuntimeError('internal invariant violated')

    monkeypatch.setattr('ipynb_scrubber.processor.decide', boom)

    nb = make_notebook(code('x = 1'))
    with pytest.raises(RuntimeError, match='internal invariant violated'):
        process_notebook(nb, OPTS)


def test_input_notebook_is_untouched_on_success(make_notebook, code):
    """process_notebook is a function, not an in-place rewrite.

    The caller keeps their notebook; the exercise version is a separate
    object, all the way down to the cells.
    """
    nb = make_notebook(
        code(
            '#| scrub-clear\nsecret = 1',
            outputs=[{'output_type': 'stream', 'text': ['1\n']}],
            execution_count=3,
        ),
        code('#| scrub-note: ex-1\nsolution = 2'),
    )
    before = copy.deepcopy(nb)

    result, _ = process_notebook(nb, OPTS)

    assert nb == before
    assert result is not nb
    assert result['cells'][0] is not nb['cells'][0]
    assert result['metadata'] is not nb['metadata']
    # ...and the copy really was scrubbed, so the comparison above means something
    assert result['cells'][0]['source'] == OPTS.clear_text


def test_input_notebook_is_untouched_after_a_mid_notebook_error():
    """Cell 0 is rewritable and cell 1 is fatal: an all-or-nothing check.

    Processing is atomic, so a failure part way through leaves the caller's
    notebook exactly as they handed it over, rather than half-scrubbed.
    """
    nb = {
        'cells': [
            {
                'cell_type': 'code',
                'source': '#| scrub-note: dupe\nx = 1',
                'metadata': {},
                'outputs': [{'output_type': 'stream', 'text': ['1\n']}],
                'execution_count': 3,
            },
            {
                'cell_type': 'code',
                'source': '#| scrub-note: dupe\ny = 2',
                'metadata': {},
                'outputs': [{'output_type': 'stream', 'text': ['2\n']}],
                'execution_count': 4,
            },
        ],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }
    before = copy.deepcopy(nb)

    with pytest.raises(ProcessingError, match='Duplicate note id'):
        process_notebook(nb, OPTS)

    assert nb == before


def test_notes_capture_original_source_before_clearing():
    nb = notebook(('code', '#| scrub-note: ex-1\nSOLUTION = 1'))
    result, notes = process_notebook(nb, OPTS)
    assert notes == {'ex-1': '#| scrub-note: ex-1\nSOLUTION = 1'}
    assert result['cells'][0]['source'] == f'# (See notes: ex-1)\n{OPTS.clear_text}'


def test_omitted_cells_are_removed():
    nb = notebook(('code', 'keep = 1'), ('code', '#| scrub-omit\ndrop = 2'))
    result, _ = process_notebook(nb, OPTS)
    assert [c['source'] for c in result['cells']] == ['keep = 1']


def test_exercise_version_metadata_is_set():
    result, _ = process_notebook(notebook(('code', 'x = 1')), OPTS)
    assert result['metadata']['exercise_version'] is True


def test_unknown_top_level_fields_are_carried_through():
    """Rebuilding the notebook must not drop keys this tool does not model."""
    nb = notebook(('code', 'x = 1'))
    nb['metadata']['kernelspec'] = {'name': 'python3'}
    nb['someday_field'] = 'keep me'

    result, _ = process_notebook(nb, OPTS)

    assert result['nbformat'] == 4
    assert result['nbformat_minor'] == 4
    assert result['someday_field'] == 'keep me'
    assert result['metadata']['kernelspec'] == {'name': 'python3'}


def test_missing_metadata_field_is_created():
    """A notebook with no top-level metadata key still gets exercise_version."""
    nb = {'cells': [], 'nbformat': 4, 'nbformat_minor': 4}
    result, _ = process_notebook(nb, OPTS)
    assert result['metadata'] == {'exercise_version': True}


def test_list_form_source_is_joined(make_notebook, code):
    """Jupyter's native on-disk format stores source as a list of lines.

    Option parsing and note capture both read through get_cell_source, which
    joins the list; a Keep'd cell's own 'source' field is left as Jupyter
    wrote it, untouched, so a note is used here to observe the joined form.
    """
    nb = make_notebook(code(['#| scrub-note: ex-1\n', 'line one\n', 'line two']))
    _, notes = process_notebook(nb, OPTS)
    assert notes['ex-1'] == '#| scrub-note: ex-1\nline one\nline two'


def test_notes_file_fences_content_as_python(tmp_path):
    path = tmp_path / 'notes.md'
    write_notes_file({'ex-1': 'SOLUTION = 1'}, path)
    content = path.read_text()

    assert '## ex-1' in content
    assert '```python\nSOLUTION = 1\n```' in content
    assert content.endswith('*Generated by ipynb-scrubber*\n')


def test_notes_file_fence_language_is_overridable(tmp_path):
    """The fence is a parameter, not a baked-in assumption that notebooks are Python."""
    path = tmp_path / 'notes.md'
    write_notes_file({'ex-1': 'x <- 1'}, path, language='r')
    assert '```r\nx <- 1\n```' in path.read_text()


def test_notes_file_creates_parent_directories(tmp_path):
    path = tmp_path / 'nested' / 'deeper' / 'notes.md'
    write_notes_file({'ex-1': 'x = 1'}, path)
    assert path.exists()


def test_notes_file_write_error_is_a_processing_error(tmp_path):
    """A parent path component that is a regular file makes mkdir fail."""
    blocker = tmp_path / 'blocker'
    blocker.write_text('not a directory')
    path = blocker / 'notes.md'

    with pytest.raises(ProcessingError, match='Error writing notes file'):
        write_notes_file({'ex-1': 'x = 1'}, path)


# --- notebook-level validation -------------------------------------------


def test_non_dict_input_errors():
    with pytest.raises(InvalidNotebookError, match='not a valid JSON object'):
        process_notebook([], OPTS)


def test_missing_cells_field_errors():
    nb = {'metadata': {}, 'nbformat': 4, 'nbformat_minor': 4}
    with pytest.raises(InvalidNotebookError, match="missing required 'cells' field"):
        process_notebook(nb, OPTS)


def test_non_list_cells_field_errors():
    nb = {'cells': 'not a list', 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 4}
    with pytest.raises(InvalidNotebookError, match="'cells' field must be a list"):
        process_notebook(nb, OPTS)


def test_non_dict_cell_errors():
    nb = {'cells': ['not a dict'], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 4}
    with pytest.raises(InvalidNotebookError, match='Cell 0 is not a valid object'):
        process_notebook(nb, OPTS)


def test_cell_missing_cell_type_errors():
    nb = {
        'cells': [{'source': 'content', 'metadata': {}}],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }
    with pytest.raises(
        InvalidNotebookError,
        match="Cell 0 is missing required 'cell_type' field",
    ):
        process_notebook(nb, OPTS)


def test_cell_invalid_cell_type_errors():
    nb = {
        'cells': [{'cell_type': 'invalid_type', 'source': 'content', 'metadata': {}}],
        'metadata': {},
        'nbformat': 4,
        'nbformat_minor': 4,
    }
    with pytest.raises(InvalidNotebookError, match='invalid cell_type'):
        process_notebook(nb, OPTS)


def test_cell_non_dict_metadata_errors(make_notebook, code):
    nb = make_notebook({'cell_type': 'code', 'source': 'x = 1', 'metadata': 'oops'})
    with pytest.raises(
        InvalidNotebookError,
        match=r"Cell 0 has invalid 'metadata' field: must be an object",
    ):
        process_notebook(nb, OPTS)


def test_cell_non_array_tags_errors(make_notebook, code):
    """tags as a bare string would make `in` do substring matching, silently

    dropping cells whose tag name happens to contain the omit tag as a
    substring; rejecting a non-array shape up front prevents that.
    """
    nb = make_notebook(
        code('x = 1', metadata={'tags': 'scrub-omit-extra'}),
    )
    with pytest.raises(
        InvalidNotebookError,
        match=r"Cell 0 has invalid 'metadata\.tags' field: "
        'must be an array of strings',
    ):
        process_notebook(nb, OPTS)


def test_cell_tags_with_non_string_items_errors(make_notebook, code):
    nb = make_notebook(code('x = 1', metadata={'tags': ['ok', 5]}))
    with pytest.raises(
        InvalidNotebookError,
        match=r"Cell 0 has invalid 'metadata\.tags' field",
    ):
        process_notebook(nb, OPTS)


def test_cell_non_string_non_list_source_errors(make_notebook):
    nb = make_notebook({'cell_type': 'code', 'source': 5, 'metadata': {}})
    with pytest.raises(
        InvalidNotebookError,
        match=r"Cell 0 has invalid 'source' field: "
        'must be a string or a list of strings',
    ):
        process_notebook(nb, OPTS)


def test_cell_source_list_with_non_string_items_errors(make_notebook):
    nb = make_notebook({'cell_type': 'code', 'source': ['ok', 5], 'metadata': {}})
    with pytest.raises(
        InvalidNotebookError,
        match=r"Cell 0 has invalid 'source' field",
    ):
        process_notebook(nb, OPTS)


# --- clearing --------------------------------------------------------------


def test_code_cell_output_and_execution_count_are_stripped(make_notebook, code):
    nb = make_notebook(
        code(
            "print('hello')",
            outputs=[{'output_type': 'stream', 'text': ['hello\n']}],
            execution_count=1,
        ),
    )
    result, _ = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == "print('hello')"
    assert 'outputs' not in result['cells'][0]
    assert 'execution_count' not in result['cells'][0]


def test_empty_notebook_is_processed(make_notebook):
    nb = make_notebook()
    result, _ = process_notebook(nb, OPTS)
    assert result['cells'] == []
    assert result['metadata']['exercise_version'] is True


def test_metadata_tag_clear_uses_configured_default(make_notebook, code):
    nb = make_notebook(code('secret = 1', metadata={'tags': ['scrub-clear']}))
    result, _ = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == OPTS.clear_text


def test_custom_clear_tag(make_notebook, code):
    """Only the configured clear tag clears; the default tag is inert."""
    nb = make_notebook(
        code('secret = 1', metadata={'tags': ['answer']}),
        code('#| scrub-clear\nother_secret = 2'),
    )
    opts = ScrubbingOptions(clear_tag='answer')
    result, _ = process_notebook(nb, opts)
    assert result['cells'][0]['source'] == opts.clear_text
    assert 'other_secret' in result['cells'][1]['source']


def test_custom_clear_text(make_notebook, code):
    nb = make_notebook(code('secret = 1', metadata={'tags': ['scrub-clear']}))
    opts = ScrubbingOptions(clear_text='# YOUR CODE HERE')
    result, _ = process_notebook(nb, opts)
    assert result['cells'][0]['source'] == '# YOUR CODE HERE'


def test_quarto_clear_with_inline_text_and_empty_text(make_notebook, code):
    nb = make_notebook(
        code('#| scrub-clear: Custom replacement text\nprint("solution")'),
        code('#| scrub-clear: \nprint("empty text")'),
    )
    result, _ = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == 'Custom replacement text'
    assert result['cells'][1]['source'] == ''


def test_markdown_cell_clearing(make_notebook, markdown):
    nb = make_notebook(
        markdown(
            '<!-- scrub-clear: **Your answer here** -->\n\n'
            '## Question 1\n\nWhat is the answer?',
        ),
        markdown(
            '## Question 2\n\nThis is an answer that should be cleared.',
            metadata={'tags': ['scrub-clear']},
        ),
        markdown('<!-- scrub-clear -->\n\n## Question 3\n\nAnother answer to clear.'),
    )
    result, _ = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == '**Your answer here**'
    assert result['cells'][1]['source'] == OPTS.clear_text
    assert result['cells'][2]['source'] == OPTS.clear_text


def test_raw_cell_clearing_via_tag(make_notebook, raw):
    """Raw cells support only metadata tags, no source-based options."""
    nb = make_notebook(
        raw('$$\\int_0^1 x^2 dx = \\frac{1}{3}$$', metadata={'tags': ['scrub-clear']}),
    )
    result, _ = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == OPTS.clear_text


def test_multiline_clear_text_option_survives(make_notebook, code):
    """A multi-line clear_text value (however configured) reaches the cell."""
    nb = make_notebook(code('secret', metadata={'tags': ['scrub-clear']}))
    opts = ScrubbingOptions(clear_text='def add(a, b):\n    # TODO\n    pass')
    result, _ = process_notebook(nb, opts)
    assert result['cells'][0]['source'] == 'def add(a, b):\n    # TODO\n    pass'


def test_code_cell_multiline_block(make_notebook, code):
    """Multi-line replacement via a block scalar in a code cell."""
    nb = make_notebook(
        code(
            '#| scrub-clear: |\n'
            '#|   def add(a, b):\n'
            '#|       # TODO: your code here\n'
            '#|       pass\n'
            'def add(a, b):\n'
            '    return a + b',
        ),
    )
    result, _ = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == (
        'def add(a, b):\n    # TODO: your code here\n    pass'
    )


def test_markdown_cell_multiline_block(make_notebook, markdown):
    """Multi-line replacement via a block scalar in a markdown cell."""
    nb = make_notebook(
        markdown(
            '<!-- scrub-clear: |\n'
            '  **Write your answer here**\n'
            '\n'
            '  Show your work.\n'
            '-->\n'
            '## Solution',
        ),
    )
    result, _ = process_notebook(nb, OPTS)
    assert (
        result['cells'][0]['source'] == '**Write your answer here**\n\nShow your work.'
    )


def test_inline_escape_sequences(make_notebook, code):
    """Escapes are expanded in inline values."""
    nb = make_notebook(code('#| scrub-clear: line one\\nline two\nprint("x")'))
    result, _ = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == 'line one\nline two'


def test_inline_text_with_block_errors(make_notebook, code):
    """Inline text plus a block is a hard error."""
    nb = make_notebook(
        code('#| scrub-clear: some text |\n#|   more text\nprint("x")'),
    )
    with pytest.raises(
        ProcessingError,
        match=r'^Cell 0: .*both inline text and a block',
    ):
        process_notebook(nb, OPTS)


def test_inline_plus_block_errors_for_markdown(make_notebook, markdown):
    nb = make_notebook(
        markdown('<!-- scrub-clear: some text |\n  more text\n-->\n## Solution'),
    )
    with pytest.raises(ProcessingError, match='inline text and a block'):
        process_notebook(nb, OPTS)


def test_unterminated_markdown_block_errors(make_notebook, markdown):
    """An unterminated markdown block is a hard error naming the cell."""
    nb = make_notebook(
        markdown('# Intro'),
        markdown('<!-- scrub-clear: |\n  never closed'),
    )
    with pytest.raises(ProcessingError, match=r'^Cell 1: Unterminated'):
        process_notebook(nb, OPTS)


# --- omitting ----------------------------------------------------------


def test_omit_via_metadata_tag(make_notebook, markdown, code):
    nb = make_notebook(
        markdown('# Keep this'),
        code("print('this should be omitted')", metadata={'tags': ['scrub-omit']}),
        code("print('keep this')"),
    )
    result, _ = process_notebook(nb, OPTS)
    sources = [c['source'] for c in result['cells']]
    assert sources == ['# Keep this', "print('keep this')"]


def test_omit_via_source_option(make_notebook, code):
    nb = make_notebook(
        code("#| scrub-omit\nprint('omit me')"),
        code("print('keep me')"),
    )
    result, _ = process_notebook(nb, OPTS)
    assert len(result['cells']) == 1
    assert 'keep me' in result['cells'][0]['source']


def test_custom_omit_tag(make_notebook, code):
    nb = make_notebook(
        code("print('remove')", metadata={'tags': ['remove-me']}),
        code("print('keep')", metadata={'tags': ['scrub-omit']}),  # default tag inert
    )
    opts = ScrubbingOptions(omit_tag='remove-me')
    result, _ = process_notebook(nb, opts)
    assert len(result['cells']) == 1
    assert result['cells'][0]['source'] == "print('keep')"


def test_omit_beats_clear_when_both_tags_present(make_notebook, code):
    nb = make_notebook(
        code('# Cell 0: normal'),
        code('# Cell 1: solution', metadata={'tags': ['scrub-clear']}),
        code('# Cell 2: omit', metadata={'tags': ['scrub-omit']}),
        code('# Cell 3: both tags', metadata={'tags': ['scrub-clear', 'scrub-omit']}),
    )
    result, _ = process_notebook(nb, OPTS)
    sources = [c['source'] for c in result['cells']]
    assert sources == ['# Cell 0: normal', OPTS.clear_text]


def test_two_source_options_on_one_cell_is_an_error(make_notebook, code):
    """Only one scrubber option per source header is allowed.

    A cell's source header may carry at most one scrubber option (Task 4);
    two source-level scrubber options, even omit + note, is a hard error
    rather than an implicit precedence, because an under-indented block
    content line would otherwise be indistinguishable from a sibling option.
    """
    nb = make_notebook(code('#| scrub-omit\n#| scrub-note: ex-1\nsecret = 1'))
    with pytest.raises(ProcessingError, match=r'only one .* option per cell'):
        process_notebook(nb, OPTS)


def test_metadata_omit_beats_source_note(make_notebook, code):
    """Omit-as-tag and note-as-source-option is allowed: omit wins.

    Unlike two source options on the same header, mixing a metadata tag
    with a source option is unambiguous, so the documented
    omit-beats-note precedence applies via guard order.
    """
    nb = make_notebook(
        code('#| scrub-note: ex-1\nsecret = 1', metadata={'tags': ['scrub-omit']}),
    )
    result, notes = process_notebook(nb, OPTS)
    assert result['cells'] == []
    assert notes == {}


def test_omit_metadata_tag_beats_note_metadata_tag(make_notebook, code):
    """A cell tagged both omit and note is omitted, not an error."""
    nb = make_notebook(
        code(
            'def solution():\n    return 42',
            metadata={'tags': ['scrub-omit', 'scrub-note']},
        ),
        code('print("kept")'),
    )
    result, _ = process_notebook(nb, OPTS)
    assert len(result['cells']) == 1
    assert result['cells'][0]['source'] == 'print("kept")'


# --- notes ---------------------------------------------------------------


def test_note_cell_captures_original_and_clears(make_notebook, code):
    nb = make_notebook(
        code('#| scrub-note: exercise-1\ndef solution():\n    return 42'),
    )
    result, notes = process_notebook(nb, OPTS)

    assert notes['exercise-1'] == (
        '#| scrub-note: exercise-1\ndef solution():\n    return 42'
    )
    assert result['cells'][0]['source'] == (
        f'# (See notes: exercise-1)\n{OPTS.clear_text}'
    )


def test_note_cell_with_custom_inline_replacement(make_notebook, code):
    nb = make_notebook(
        code(
            '#| scrub-note: my-note | # YOUR CODE HERE\ndef solution():\n    return 42',
        ),
    )
    result, notes = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == '# (See notes: my-note)\n# YOUR CODE HERE'
    assert 'my-note' in notes


@pytest.mark.parametrize(
    'source',
    [
        '#| scrub-note\ndef solution():\n    return 42',
        '#| scrub-note:\ndef solution():\n    return 42',
        '#| scrub-note: | # YOUR CODE HERE\ndef solution():\n    return 42',
        '#| scrub-note: |\n#|   # YOUR CODE HERE\ndef solution():\n    return 42',
    ],
)
def test_note_cell_without_id_errors(make_notebook, code, source):
    """A scrub-note without a usable id is an error, not a silent pass-through."""
    nb = make_notebook(code(source))
    with pytest.raises(ProcessingError, match=r'^Cell 0: .*requires an id'):
        process_notebook(nb, OPTS)


def test_note_cell_block_replacement(make_notebook, code):
    """A note's replacement text can come from a block."""
    nb = make_notebook(
        code(
            '#| scrub-note: ex-1 |\n'
            '#|   def add(a, b):\n'
            '#|       pass\n'
            'def add(a, b):\n'
            '    return a + b',
        ),
    )
    result, notes = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == (
        '# (See notes: ex-1)\ndef add(a, b):\n    pass'
    )
    assert 'ex-1' in notes


def test_note_cell_block_opener_without_body(make_notebook, code):
    """A block opener with no body clears the cell to just the note reference."""
    nb = make_notebook(code('#| scrub-note: my-id |\ndef solution():\n    return 42'))
    result, notes = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == '# (See notes: my-id)'
    assert 'my-id' in notes


@pytest.mark.parametrize(
    'source',
    [
        '#| scrub-note: ex-1|# YOUR CODE HERE\nprint("x")',
        '#| scrub-note: ex-1 |# YOUR CODE HERE\nprint("x")',
        '#| scrub-note: ex-1 | # YOUR CODE HERE\nprint("x")',
    ],
)
def test_note_separator_is_whitespace_insensitive(make_notebook, code, source):
    """The id/replacement split is on the first pipe, regardless of spacing."""
    nb = make_notebook(code(source))
    result, _ = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == '# (See notes: ex-1)\n# YOUR CODE HERE'


def test_note_cell_non_code_errors(make_notebook, markdown):
    """A note tag on a non-code cell is a hard error, not a silent no-op."""
    nb = make_notebook(markdown('<!-- scrub-note: md-note -->\n## Solution'))
    with pytest.raises(
        ProcessingError,
        match=r'^Cell 0: .*only supported on code cells',
    ):
        process_notebook(nb, OPTS)


def test_note_cell_inline_text_with_block_errors(make_notebook, code):
    """A note with both inline replacement text and a block is a hard error."""
    nb = make_notebook(
        code(
            '#| scrub-note: ex-1 | # TODO |\n'
            '#|   # YOUR CODE HERE\n'
            'def solution():\n'
            '    return 42',
        ),
    )
    with pytest.raises(
        ProcessingError,
        match=r'^Cell 0: .*both inline text and a block',
    ):
        process_notebook(nb, OPTS)


def test_note_cell_id_then_block_is_not_an_error(make_notebook, code):
    """An id with a bare block opener is the ordinary multi-line note form."""
    nb = make_notebook(
        code(
            '#| scrub-note: ex-1 |\n'
            '#|   # YOUR CODE HERE\n'
            'def solution():\n'
            '    return 42',
        ),
    )
    result, notes = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == '# (See notes: ex-1)\n# YOUR CODE HERE'
    assert 'ex-1' in notes


def test_note_cell_inline_text_without_block_is_not_an_error(make_notebook, code):
    """Inline replacement text with no block remains the ordinary inline form."""
    nb = make_notebook(
        code('#| scrub-note: ex-1 | # TODO\ndef solution():\n    return 42'),
    )
    result, notes = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == '# (See notes: ex-1)\n# TODO'
    assert 'ex-1' in notes


def test_note_cell_with_custom_note_tag(make_notebook, code):
    """A configured custom note_tag, not just 'scrub-note', is recognized in source."""
    nb = make_notebook(
        code('#| solution-note: custom-id\ndef custom_solution():\n    return 1'),
    )
    opts = ScrubbingOptions(note_tag='solution-note')
    result, notes = process_notebook(nb, opts)
    assert notes['custom-id'] == (
        '#| solution-note: custom-id\ndef custom_solution():\n    return 1'
    )
    assert result['cells'][0]['source'] == (
        f'# (See notes: custom-id)\n{opts.clear_text}'
    )


def test_note_absent_on_markdown_and_raw_cells_is_fine(make_notebook, markdown, raw):
    """A cell without a note option is untouched by the note check."""
    nb = make_notebook(
        markdown('## Solution'),
        raw('#| scrub-note: raw-note\nraw content'),
    )
    result, notes = process_notebook(nb, OPTS)
    assert result['cells'][0]['source'] == '## Solution'
    assert result['cells'][1]['source'] == '#| scrub-note: raw-note\nraw content'
    assert notes == {}


@pytest.mark.parametrize(
    ('cell_type', 'source'),
    [
        ('code', 'def solution():\n    return 42'),
        ('markdown', '## Solution\n\nThe answer is 42.'),
        ('raw', 'raw solution content'),
    ],
)
def test_note_metadata_tag_errors(make_notebook, cell_type, source):
    """The note tag as Jupyter cell metadata is a hard error, never a no-op."""
    nb = make_notebook(
        {
            'cell_type': cell_type,
            'source': source,
            'metadata': {'tags': ['scrub-note']},
        },
    )
    with pytest.raises(
        ProcessingError,
        match=r'^Cell 0: .*not supported as a cell tag',
    ):
        process_notebook(nb, OPTS)


def test_note_metadata_tag_with_custom_tag_errors(make_notebook, code):
    """The error follows a custom note_tag rather than the default name."""
    nb = make_notebook(
        code('def solution():\n    return 42', metadata={'tags': ['keepme']}),
    )
    opts = ScrubbingOptions(note_tag='keepme')
    with pytest.raises(
        ProcessingError,
        match="Option 'keepme' is not supported as a cell tag",
    ):
        process_notebook(nb, opts)


def test_non_object_notebook_metadata_is_rejected():
    """Malformed top-level metadata is bad input, not an internal bug.

    The processor merges ``exercise_version`` into this mapping, so a
    non-object here would otherwise surface as a TypeError traceback.
    """
    for bad in (None, 'oops', 42, []):
        with pytest.raises(
            InvalidNotebookError,
            match="Notebook has invalid 'metadata' field",
        ):
            process_notebook({'cells': [], 'metadata': bad}, OPTS)


def test_notebook_without_metadata_is_accepted(code):
    """metadata is optional; the processor supplies it."""
    result, _ = process_notebook({'cells': [code('x = 1')]}, OPTS)
    assert result['metadata'] == {'exercise_version': True}


def test_notes_fence_follows_the_notebook_language(tmp_path, code):
    """A non-Python notebook gets its notes fenced in its own language."""
    nb = {
        'cells': [code('#| scrub-note: ex-1\nx <- 1')],
        'metadata': {'language_info': {'name': 'r'}},
    }
    _, notes = process_notebook(nb, OPTS)
    out = tmp_path / 'notes.md'
    write_notes_file(notes, out, get_notebook_language(nb))
    assert '```r\n#| scrub-note: ex-1\nx <- 1\n```' in out.read_text()
