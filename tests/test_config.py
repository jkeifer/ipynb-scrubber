import dataclasses
import tomllib

from pathlib import Path

import pytest

from ipynb_scrubber.actions import OPTIONS, ScrubbingOptions
from ipynb_scrubber.config import FileEntry, ProjectConfig, find_config
from ipynb_scrubber.exceptions import ScrubberError


def test_file_level_empty_clear_text_is_preserved():
    entry = FileEntry.from_dict(
        {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-text': ''},
        ScrubbingOptions(),
    )
    assert entry.options.clear_text == ''


def test_global_empty_clear_text_is_preserved():
    assert ScrubbingOptions.from_dict({'clear-text': ''}).clear_text == ''


def test_absent_file_option_falls_back_to_global():
    entry = FileEntry.from_dict(
        {'input': 'a.ipynb', 'output': 'b.ipynb'},
        ScrubbingOptions(clear_text='GLOBAL'),
    )
    assert entry.options.clear_text == 'GLOBAL'


def test_file_option_overrides_global():
    entry = FileEntry.from_dict(
        {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-tag': 'mine'},
        ScrubbingOptions(clear_tag='theirs'),
    )
    assert entry.options.clear_tag == 'mine'


def test_merged_with_is_presence_based_not_truthiness_based():
    merged = ScrubbingOptions(clear_text='GLOBAL', clear_tag='theirs').merged_with(
        {'clear-text': ''},
    )
    assert merged.clear_text == ''
    assert merged.clear_tag == 'theirs'


def test_config_resolves_options_per_file():
    config = ProjectConfig.from_dict(
        {
            'options': {'clear-text': 'GLOBAL'},
            'files': [
                {'input': 'a.ipynb', 'output': 'a-out.ipynb'},
                {'input': 'b.ipynb', 'output': 'b-out.ipynb', 'clear-text': 'MINE'},
            ],
        },
    )
    assert [f.options.clear_text for f in config.files] == ['GLOBAL', 'MINE']


def test_every_registered_option_gets_a_cli_flag():
    """The registry is the single source of truth, including for the CLI."""
    from ipynb_scrubber.cli import build_parser

    args = build_parser().parse_args(['scrub-notebook'])

    for option in OPTIONS:
        assert getattr(args, option.field) == getattr(ScrubbingOptions(), option.field)
        assert option.help, f'{option.key} has no help text'


def test_markdown_clear_text_is_a_separate_option():
    """A cleared markdown cell must not render its placeholder as a heading."""
    defaults = ScrubbingOptions()
    assert defaults.clear_text_markdown == '*TODO: Implement this*'
    assert defaults.clear_text_markdown != defaults.clear_text


def test_markdown_clear_text_is_configurable_globally():
    opts = ScrubbingOptions.from_dict({'clear-text-markdown': '_do this_'})
    assert opts.clear_text_markdown == '_do this_'


def test_markdown_clear_text_is_overridable_per_file():
    entry = FileEntry.from_dict(
        {
            'input': 'a.ipynb',
            'output': 'b.ipynb',
            'clear-text-markdown': '_mine_',
        },
        ScrubbingOptions(clear_text_markdown='_global_'),
    )
    assert entry.options.clear_text_markdown == '_mine_'


def test_raw_clear_text_is_a_separate_option():
    """A raw cell is emitted verbatim, so its placeholder carries no markup."""
    defaults = ScrubbingOptions()
    assert defaults.clear_text_raw == 'TODO: Implement this'
    assert defaults.clear_text_raw != defaults.clear_text


def test_raw_clear_text_is_configurable_globally():
    opts = ScrubbingOptions.from_dict({'clear-text-raw': 'do this'})
    assert opts.clear_text_raw == 'do this'


def test_raw_clear_text_is_overridable_per_file():
    entry = FileEntry.from_dict(
        {
            'input': 'a.ipynb',
            'output': 'b.ipynb',
            'clear-text-raw': 'mine',
        },
        ScrubbingOptions(clear_text_raw='global'),
    )
    assert entry.options.clear_text_raw == 'mine'


def test_note_reference_is_configurable_globally():
    """The marker is a comment, and not every kernel spells one with '#'."""
    opts = ScrubbingOptions.from_dict({'note-reference': '// (See notes: {id})'})
    assert opts.note_reference == '// (See notes: {id})'


def test_note_reference_is_overridable_per_file():
    entry = FileEntry.from_dict(
        {
            'input': 'a.ipynb',
            'output': 'b.ipynb',
            'note-reference': '-- see {id}',
        },
        ScrubbingOptions(note_reference='# see {id}'),
    )
    assert entry.options.note_reference == '-- see {id}'


@pytest.mark.parametrize('key', [option.key for option in OPTIONS])
@pytest.mark.parametrize('value', [5, None, 1.5, True, ['x'], {'a': 1}])
def test_option_values_of_the_wrong_type_are_rejected(key, value):
    """An untyped TOML value must not reach the dataclass unchecked.

    Which values every option refuses, and nothing about how it says so: the
    wording is one message, and the test below is where it is pinned.
    """
    with pytest.raises(ScrubberError):
        ScrubbingOptions.from_dict({key: value})


def test_wrong_type_error_names_the_type_and_the_value():
    with pytest.raises(ScrubberError, match=r'clear-tag must be str.*int: 5'):
        ScrubbingOptions.from_dict({'clear-tag': 5})


@pytest.mark.parametrize('key', [option.key for option in OPTIONS])
def test_file_level_option_of_the_wrong_type_is_rejected(key):
    with pytest.raises(ScrubberError, match=f'{key} must be str'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', key: 5},
            ScrubbingOptions(),
        )


def test_direct_construction_with_a_wrong_type_is_rejected():
    """__post_init__ guards replace() and hand construction alike."""
    with pytest.raises(ScrubberError, match='clear-text must be str'):
        ScrubbingOptions(clear_text=5)  # type: ignore[arg-type]


@pytest.mark.parametrize('key', ['input', 'output', 'notes-file'])
def test_file_entry_path_of_the_wrong_type_is_rejected(key):
    data = {'input': 'a.ipynb', 'output': 'b.ipynb'}
    data[key] = 5
    with pytest.raises(ScrubberError, match=f'{key} must be str'):
        FileEntry.from_dict(data, ScrubbingOptions())


def test_empty_notes_file_is_rejected():
    """Presence-based: an empty path was asked for and cannot be written."""
    with pytest.raises(ScrubberError, match='notes-file must not be empty'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'notes-file': ''},
            ScrubbingOptions(),
        )


def test_absent_notes_file_is_none():
    entry = FileEntry.from_dict(
        {'input': 'a.ipynb', 'output': 'b.ipynb'},
        ScrubbingOptions(),
    )
    assert entry.notes_file is None


def test_present_notes_file_is_a_path():
    entry = FileEntry.from_dict(
        {'input': 'a.ipynb', 'output': 'b.ipynb', 'notes-file': 'n.md'},
        ScrubbingOptions(),
    )
    assert entry.notes_file == Path('n.md')


def test_scrubbing_onto_the_input_is_rejected():
    """The whole point is an exercise copy; the original has to survive it."""
    with pytest.raises(ScrubberError, match='input and output must name'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'a.ipynb'},
            ScrubbingOptions(),
        )


def test_notes_file_onto_the_input_is_rejected():
    with pytest.raises(ScrubberError, match='notes-file and input must name'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'notes-file': 'a.ipynb'},
            ScrubbingOptions(),
        )


def test_notes_file_onto_the_output_is_rejected():
    """Both are written, so one would silently overwrite the other."""
    with pytest.raises(ScrubberError, match='notes-file and output must name'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'notes-file': 'b.ipynb'},
            ScrubbingOptions(),
        )


def test_direct_construction_onto_the_input_is_rejected():
    """__post_init__, so a hand-built entry gets the guarantee a config does."""
    with pytest.raises(ScrubberError, match='input and output must name'):
        FileEntry(input=Path('a.ipynb'), output=Path('a.ipynb'))


def test_a_leading_dot_slash_does_not_disguise_the_same_path():
    """Path() normalises './a.ipynb' on the way in, so this is one path."""
    with pytest.raises(ScrubberError, match='input and output must name'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': './a.ipynb'},
            ScrubbingOptions(),
        )


def test_two_entries_writing_the_same_output_are_rejected():
    """Only visible with the whole batch in hand, so ProjectConfig checks it."""
    with pytest.raises(ScrubberError, match=r'files\[0\]\.output and files\[1\]'):
        ProjectConfig.from_dict(
            {
                'files': [
                    {'input': 'a.ipynb', 'output': 'out.ipynb'},
                    {'input': 'b.ipynb', 'output': 'out.ipynb'},
                ],
            },
        )


def test_two_entries_writing_the_same_notes_file_are_rejected():
    with pytest.raises(ScrubberError, match=r'files\[0\]\.notes-file and files\[1\]'):
        ProjectConfig.from_dict(
            {
                'files': [
                    {'input': 'a.ipynb', 'output': 'a-out.ipynb', 'notes-file': 'n.md'},
                    {'input': 'b.ipynb', 'output': 'b-out.ipynb', 'notes-file': 'n.md'},
                ],
            },
        )


def test_an_entry_writing_over_another_entrys_input_is_rejected():
    with pytest.raises(ScrubberError, match=r'files\[0\]\.output writes b\.ipynb'):
        ProjectConfig.from_dict(
            {
                'files': [
                    {'input': 'a.ipynb', 'output': 'b.ipynb'},
                    {'input': 'b.ipynb', 'output': 'c.ipynb'},
                ],
            },
        )


def test_an_entrys_notes_file_over_an_earlier_entrys_input_is_rejected():
    """A notes file is as capable of destroying a source as an output is."""
    with pytest.raises(ScrubberError, match=r'files\[1\]\.notes-file writes a\.ipynb'):
        ProjectConfig.from_dict(
            {
                'files': [
                    {'input': 'a.ipynb', 'output': 'a-out.ipynb'},
                    {
                        'input': 'b.ipynb',
                        'output': 'b-out.ipynb',
                        'notes-file': 'a.ipynb',
                    },
                ],
            },
        )


def test_distinct_entries_sharing_an_input_are_allowed():
    """Reading one notebook twice destroys nothing; only writes collide."""
    config = ProjectConfig.from_dict(
        {
            'files': [
                {'input': 'a.ipynb', 'output': 'plain.ipynb'},
                {'input': 'a.ipynb', 'output': 'harder.ipynb', 'clear-text': 'X'},
            ],
        },
    )
    assert [f.output for f in config.files] == [
        Path('plain.ipynb'),
        Path('harder.ipynb'),
    ]


def test_unknown_global_option_errors():
    with pytest.raises(ScrubberError, match='claer-tag'):
        ScrubbingOptions.from_dict({'claer-tag': 'x'})


def test_unknown_file_entry_key_errors():
    with pytest.raises(ScrubberError, match='notes-fil'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'notes-fil': 'n.md'},
            ScrubbingOptions(),
        )


def test_field_name_spelling_is_not_a_valid_toml_key():
    """The table maps TOML spellings only; the dataclass field name is a typo."""
    with pytest.raises(ScrubberError, match='file entry key'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear_text': 'x'},
            ScrubbingOptions(),
        )


def test_unknown_top_level_key_errors():
    with pytest.raises(ScrubberError, match='fils'):
        ProjectConfig.from_dict(
            {'files': [{'input': 'a.ipynb', 'output': 'b.ipynb'}], 'fils': []},
        )


@pytest.mark.parametrize('missing', ['input', 'output'])
def test_file_entry_requires_input_and_output(missing):
    data = {'input': 'a.ipynb', 'output': 'b.ipynb'}
    del data[missing]
    with pytest.raises(ScrubberError, match=missing):
        FileEntry.from_dict(data, ScrubbingOptions())


def test_config_requires_at_least_one_file():
    with pytest.raises(ScrubberError, match='at least one file'):
        ProjectConfig.from_dict({})


def test_direct_construction_defaults_to_default_options():
    entry = FileEntry(input=Path('a.ipynb'), output=Path('b.ipynb'))
    assert entry.options == ScrubbingOptions()


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


def test_an_unusable_tag_name_is_rejected_from_dict():
    with pytest.raises(ScrubberError, match='must start with a letter'):
        ScrubbingOptions.from_dict({'omit-tag': 'not a name'})


def test_file_override_with_an_unusable_tag_name_is_rejected():
    """The merge goes through replace(), so __post_init__ catches it."""
    with pytest.raises(ScrubberError, match='must start with a letter'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-tag': 'has space'},
            ScrubbingOptions(),
        )


def test_a_tag_name_yaml_reads_as_a_bool_is_rejected_from_dict():
    with pytest.raises(ScrubberError, match='must be a name YAML reads back as text'):
        ScrubbingOptions.from_dict({'omit-tag': 'no'})


def test_file_override_with_a_tag_name_yaml_reads_as_a_bool_is_rejected():
    """The merge goes through replace(), so __post_init__ catches it."""
    with pytest.raises(ScrubberError, match='must be a name YAML reads back as text'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-tag': 'null'},
            ScrubbingOptions(),
        )


def test_colliding_tags_are_rejected_from_dict():
    with pytest.raises(ScrubberError, match='must all be distinct'):
        ScrubbingOptions.from_dict({'clear-tag': 'dup', 'omit-tag': 'dup'})


def test_file_override_colliding_with_inherited_tag_is_rejected():
    """The merge goes through replace(), so __post_init__ catches it."""
    with pytest.raises(ScrubberError, match='must all be distinct'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-tag': 'scrub-omit'},
            ScrubbingOptions(),
        )


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


def test_from_file_missing_path_errors():
    with pytest.raises(ScrubberError, match='Config file not found'):
        ProjectConfig.from_file(Path('/nonexistent/does-not-exist.toml'))


def test_from_file_unreadable_path_errors(tmp_path):
    """A path that exists but can't be opened as TOML (e.g. a directory)."""
    a_directory = tmp_path / 'not-a-file.toml'
    a_directory.mkdir()
    with pytest.raises(ScrubberError, match=r'Error reading .*not-a-file\.toml'):
        ProjectConfig.from_file(a_directory)


def test_from_file_does_not_swallow_unexpected_errors(tmp_path, monkeypatch):
    """Only OSError and TOMLDecodeError become friendly errors."""
    config = tmp_path / '.ipynb-scrubber.toml'
    config.write_text('[[files]]\ninput = "a.ipynb"\noutput = "b.ipynb"\n')

    def boom(*args, **kwargs):
        raise MemoryError('out of memory')

    monkeypatch.setattr(tomllib, 'load', boom)

    with pytest.raises(MemoryError):
        ProjectConfig.from_file(config)


def test_find_config_errors_on_unparsable_pyproject_toml(tmp_path):
    """A broken pyproject.toml during upward search is fatal, not skipped.

    We can't know whether the broken file would have contained a
    [tool.ipynb-scrubber] section, so neither "keep searching" nor "use a
    config found higher up" is a sound conclusion.
    """
    (tmp_path / 'pyproject.toml').write_text('not valid toml [[[')
    with pytest.raises(ScrubberError, match=r'pyproject\.toml.*Fix or remove'):
        find_config(tmp_path)


def test_find_config_errors_on_unreadable_pyproject_toml(tmp_path):
    """A pyproject.toml that exists but can't be opened (e.g. a directory)."""
    (tmp_path / 'pyproject.toml').mkdir()
    with pytest.raises(ScrubberError, match=r'pyproject\.toml.*Fix or remove'):
        find_config(tmp_path)


def test_find_config_skips_pyproject_toml_without_our_section(tmp_path):
    """A readable pyproject.toml with no [tool.ipynb-scrubber] is legitimate

    and the search must keep going upward to find a real config.
    """
    subdir = tmp_path / 'sub'
    subdir.mkdir()
    (subdir / 'pyproject.toml').write_text('[tool.other]\nkey = "value"\n')
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.ipynb-scrubber]\n[[tool.ipynb-scrubber.files]]\n'
        'input = "a.ipynb"\noutput = "b.ipynb"\n',
    )
    found = find_config(subdir)
    assert found is not None
    assert found[0] == tmp_path / 'pyproject.toml'


def test_find_config_returns_the_parsed_config(tmp_path):
    """The search parses the file it finds so callers need not re-read it."""
    (tmp_path / '.ipynb-scrubber.toml').write_text(
        '[[files]]\ninput = "a.ipynb"\noutput = "b.ipynb"\n',
    )
    found = find_config(tmp_path)
    assert found is not None
    path, data = found
    assert path == tmp_path / '.ipynb-scrubber.toml'
    assert data == {'files': [{'input': 'a.ipynb', 'output': 'b.ipynb'}]}


def test_find_config_returns_none_when_nothing_is_found(tmp_path):
    assert find_config(tmp_path / 'nowhere') is None
