import tomllib

from pathlib import Path

import pytest

from ipynb_scrubber.config import FileEntry, ProjectConfig, find_config
from ipynb_scrubber.exceptions import ScrubberError
from ipynb_scrubber.options import OPTIONS, ScrubbingOptions


def test_file_level_empty_clear_text_is_preserved():
    """The presence rule survives the per-file override path.

    Not the rule itself -- that is test_options.py's, on ScrubbingOptions --
    but that a file entry hands its keys over with their emptiness intact.
    """
    entry = FileEntry.from_dict(
        {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-text': ''},
        ScrubbingOptions(),
    )
    assert entry.options.clear_text == ''


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


def test_markdown_clear_text_is_overridable_per_file():
    """The option survives the per-file override path.

    That the option exists and that a config mapping sets it is
    test_options.py's; this is only that a file entry can override it.
    """
    entry = FileEntry.from_dict(
        {
            'input': 'a.ipynb',
            'output': 'b.ipynb',
            'clear-text-markdown': '_mine_',
        },
        ScrubbingOptions(clear_text_markdown='_global_'),
    )
    assert entry.options.clear_text_markdown == '_mine_'


def test_raw_clear_text_is_overridable_per_file():
    """The option survives the per-file override path.

    That the option exists and that a config mapping sets it is
    test_options.py's; this is only that a file entry can override it.
    """
    entry = FileEntry.from_dict(
        {
            'input': 'a.ipynb',
            'output': 'b.ipynb',
            'clear-text-raw': 'mine',
        },
        ScrubbingOptions(clear_text_raw='global'),
    )
    assert entry.options.clear_text_raw == 'mine'


def test_note_reference_is_overridable_per_file():
    """The option survives the per-file override path.

    That the option exists and that a config mapping sets it is
    test_options.py's; this is only that a file entry can override it.
    """
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
def test_file_level_option_of_the_wrong_type_is_rejected(key):
    """The type check survives the per-file override path.

    Which values every option refuses, and how it says so, is test_options.py's;
    this is that a file entry's override reaches that check at all.
    """
    with pytest.raises(ScrubberError, match=f'{key} must be str'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', key: 5},
            ScrubbingOptions(),
        )


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


def test_unknown_file_entry_key_errors():
    """A file entry takes the option keys plus its own three, and nothing else.

    The option table has its own version of this in test_options.py; the two
    key sets differ, so neither test covers the other.
    """
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


def test_file_override_with_an_unusable_tag_name_is_rejected():
    """The merge goes through replace(), so __post_init__ catches it.

    The name rule itself is test_options.py's; this is that a per-file override
    is not a way around it.
    """
    with pytest.raises(ScrubberError, match='must start with a letter'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-tag': 'has space'},
            ScrubbingOptions(),
        )


def test_file_override_with_a_tag_name_yaml_reads_as_a_bool_is_rejected():
    """The merge goes through replace(), so __post_init__ catches it.

    The name rule itself is test_options.py's; this is that a per-file override
    is not a way around it.
    """
    with pytest.raises(ScrubberError, match='must be a name YAML reads back as text'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-tag': 'null'},
            ScrubbingOptions(),
        )


def test_file_override_colliding_with_inherited_tag_is_rejected():
    """The merge goes through replace(), so __post_init__ catches it.

    The distinctness rule itself is test_options.py's; this is that an override
    colliding with a tag it inherited is not a way around it.
    """
    with pytest.raises(ScrubberError, match='must all be distinct'):
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-tag': 'scrub-omit'},
            ScrubbingOptions(),
        )


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
