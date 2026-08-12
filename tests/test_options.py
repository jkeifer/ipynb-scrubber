import dataclasses

import pytest

from ipynb_scrubber.exceptions import ScrubberError
from ipynb_scrubber.notebook import CELL_TYPES
from ipynb_scrubber.options import (
    _CLEAR_TEXT_FIELDS,
    MARKERS,
    OPTIONS,
    ScrubbingOptions,
)


def test_markers_are_considered_omit_then_note_then_clear():
    """The registry's order is the precedence order, so it is load-bearing.

    Omit first because dropping a cell subsumes every rewrite of it, and note
    before clear because a note is a clear that also files away what it
    removed. Reordering the table silently changes what a cell carrying two
    markers becomes.
    """
    assert [option.key for option in MARKERS] == ['omit-tag', 'note-tag', 'clear-tag']


def test_every_cell_type_has_its_own_clear_text():
    """The lookup is total over the cell types, so it needs no default.

    Clearing indexes by cell type with nothing to fall back on, which is only
    safe while the two agree. A type validation lets through but this table
    does not name would be a KeyError on a notebook the tool accepted.
    """
    assert set(_CLEAR_TEXT_FIELDS) == set(CELL_TYPES)


def test_markdown_clear_text_is_a_separate_option():
    """A cleared markdown cell must not render its placeholder as a heading."""
    defaults = ScrubbingOptions()
    assert defaults.clear_text_markdown == '*TODO: Implement this*'
    assert defaults.clear_text_markdown != defaults.clear_text


def test_raw_clear_text_is_a_separate_option():
    """A raw cell is emitted verbatim, so its placeholder carries no markup."""
    defaults = ScrubbingOptions()
    assert defaults.clear_text_raw == 'TODO: Implement this'
    assert defaults.clear_text_raw != defaults.clear_text


def test_direct_construction_with_a_wrong_type_is_rejected():
    """__post_init__ guards replace() and hand construction alike."""
    with pytest.raises(ScrubberError, match='clear-text must be str'):
        ScrubbingOptions(clear_text=5)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    'kwargs',
    [
        {'clear_tag': 'x', 'omit_tag': 'x'},
        {'clear_tag': 'x', 'note_tag': 'x'},
        {'omit_tag': 'x', 'note_tag': 'x'},
    ],
)
def test_colliding_tags_are_rejected(kwargs):
    """Tags are matched as a set, so a collision would silently drop one."""
    with pytest.raises(ScrubberError, match='must all be distinct'):
        ScrubbingOptions(**kwargs)


@pytest.mark.parametrize(
    'name',
    ['', ' ', 'a b', '.*', '-x', '#foo', '1st', 'a:b'],
)
def test_unusable_tag_names_are_rejected(name):
    """A tag is written as a YAML key, so it has to survive that as itself."""
    with pytest.raises(ScrubberError, match='must start with a letter'):
        ScrubbingOptions(omit_tag=name)


@pytest.mark.parametrize(
    'name',
    ['yes', 'no', 'on', 'off', 'true', 'false', 'null', 'Yes', 'OFF', 'NULL'],
)
def test_tag_names_yaml_does_not_read_as_text_are_rejected(name):
    """These spell a YAML key that comes back as a bool or None, not a name.

    The option would be written into a header where an option goes and arrive
    under a key no lookup by name finds, so the cell would ship unscrubbed.
    """
    with pytest.raises(ScrubberError, match='must be a name YAML reads back as text'):
        ScrubbingOptions(omit_tag=name)


@pytest.mark.parametrize('name', ['scrub-omit', 'y', 'n', 'note', 'yEs', 'Drop_me-2'])
def test_ordinary_tag_names_are_accepted(name):
    """'y' and 'n' are not booleans to PyYAML's resolver, only 'yes'/'no' are."""
    assert ScrubbingOptions(omit_tag=name).omit_tag == name


@pytest.mark.parametrize(
    'field_name',
    [f.name for f in dataclasses.fields(ScrubbingOptions)],
)
def test_options_cannot_be_mutated_after_construction(field_name):
    """Every rule above is checked in __post_init__ and nowhere else.

    An assignment would skip all of them, leaving an instance holding a value
    the constructor rejects — 'no' as a tag name is the whole of the check
    above, defeated. Frozen is what makes those checks the only way in.
    """
    opts = ScrubbingOptions()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(opts, field_name, 'no')


def test_replace_still_revalidates():
    """Freezing must not cost the check replace() runs for per-file overrides."""
    with pytest.raises(ScrubberError, match='must be a name YAML reads back as text'):
        dataclasses.replace(ScrubbingOptions(), omit_tag='no')


def test_merged_with_is_presence_based_not_truthiness_based():
    merged = ScrubbingOptions(clear_text='GLOBAL', clear_tag='theirs').merged_with(
        {'clear-text': ''},
    )
    assert merged.clear_text == ''
    assert merged.clear_tag == 'theirs'


def test_global_empty_clear_text_is_preserved():
    """Presence decides in from_dict too, so '' is a value and not an absence.

    The rule itself. test_config.py holds its twin, which pins that a file
    entry's override path reaches this rather than restating it.
    """
    assert ScrubbingOptions.from_dict({'clear-text': ''}).clear_text == ''


def test_markdown_clear_text_is_configurable_globally():
    """A config mapping can replace the markdown placeholder.

    The option itself. Its twin in test_config.py pins only that a per-file
    override reaches it, so neither test covers the other.
    """
    opts = ScrubbingOptions.from_dict({'clear-text-markdown': '_do this_'})
    assert opts.clear_text_markdown == '_do this_'


def test_raw_clear_text_is_configurable_globally():
    """A config mapping can replace the raw placeholder.

    The option itself. Its twin in test_config.py pins only that a per-file
    override reaches it, so neither test covers the other.
    """
    opts = ScrubbingOptions.from_dict({'clear-text-raw': 'do this'})
    assert opts.clear_text_raw == 'do this'


def test_note_reference_is_configurable_globally():
    """The marker is a comment, and not every kernel spells one with '#'.

    The option itself. Its twin in test_config.py pins only that a per-file
    override reaches it, so neither test covers the other.
    """
    opts = ScrubbingOptions.from_dict({'note-reference': '// (See notes: {id})'})
    assert opts.note_reference == '// (See notes: {id})'


@pytest.mark.parametrize('key', [option.key for option in OPTIONS])
@pytest.mark.parametrize('value', [5, None, 1.5, True, ['x'], {'a': 1}])
def test_option_values_of_the_wrong_type_are_rejected(key, value):
    """An untyped TOML value must not reach the dataclass unchecked.

    Which values every option refuses, and nothing about how it says so: the
    wording is one message, and the test below is where it is pinned. The twin
    in test_config.py pins that a file entry's override path reaches this rule,
    not the rule again.
    """
    with pytest.raises(ScrubberError):
        ScrubbingOptions.from_dict({key: value})


def test_wrong_type_error_names_the_type_and_the_value():
    with pytest.raises(ScrubberError, match=r'clear-tag must be str.*int: 5'):
        ScrubbingOptions.from_dict({'clear-tag': 5})


def test_unknown_global_option_errors():
    """An option table takes the option keys and nothing else.

    Its counterpart in test_config.py is a different key table -- a file entry
    also takes input, output and notes-file -- and not this rule again.
    """
    with pytest.raises(ScrubberError, match='claer-tag'):
        ScrubbingOptions.from_dict({'claer-tag': 'x'})
