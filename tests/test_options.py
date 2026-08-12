import dataclasses

import pytest

from ipynb_scrubber.exceptions import ScrubberError
from ipynb_scrubber.notebook import CELL_TYPES
from ipynb_scrubber.options import _CLEAR_TEXT_FIELDS, MARKERS, ScrubbingOptions


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
