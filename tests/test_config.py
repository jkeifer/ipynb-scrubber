import tomllib

from pathlib import Path

import pytest

from ipynb_scrubber.config import (
    FileEntry,
    ProjectConfig,
    ScrubbingOptions,
    find_config,
)
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


def test_cli_defaults_match_dataclass_defaults():
    import argparse

    from ipynb_scrubber.cli import ScrubNotebook

    parser = argparse.ArgumentParser()
    ScrubNotebook().set_args(parser)
    args = parser.parse_args([])
    defaults = ScrubbingOptions()

    assert args.clear_tag == defaults.clear_tag
    assert args.clear_text == defaults.clear_text
    assert args.omit_tag == defaults.omit_tag
    assert args.note_tag == defaults.note_tag


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
    """KEYS maps TOML spellings only; the dataclass field name is a typo."""
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
