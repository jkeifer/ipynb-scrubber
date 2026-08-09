from pathlib import Path

import pytest

from ipynb_scrubber.config import FileEntry, ProjectConfig, ScrubbingOptions
from ipynb_scrubber.exceptions import ScrubberError


def test_file_level_empty_clear_text_is_preserved():
    entry = FileEntry.from_dict(
        {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-text': ''},
    )
    assert entry.get_options(ScrubbingOptions()).clear_text == ''


def test_global_empty_clear_text_is_preserved():
    assert ScrubbingOptions.from_dict({'clear-text': ''}).clear_text == ''


def test_absent_file_option_falls_back_to_global():
    entry = FileEntry.from_dict({'input': 'a.ipynb', 'output': 'b.ipynb'})
    merged = entry.get_options(ScrubbingOptions(clear_text='GLOBAL'))
    assert merged.clear_text == 'GLOBAL'


def test_file_option_overrides_global():
    entry = FileEntry.from_dict(
        {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear-tag': 'mine'},
    )
    merged = entry.get_options(ScrubbingOptions(clear_tag='theirs'))
    assert merged.clear_tag == 'mine'


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
        FileEntry.from_dict(data)


def test_config_requires_at_least_one_file():
    with pytest.raises(ScrubberError, match='at least one file'):
        ProjectConfig.from_dict({})


def test_direct_construction_rejects_bogus_override_key():
    """A bad override is a ScrubberError, not a TypeError from replace()."""
    with pytest.raises(ScrubberError, match='file entry override'):
        FileEntry(
            input=Path('a.ipynb'),
            output=Path('b.ipynb'),
            overrides={'not_a_field': 'x'},
        )


def test_direct_construction_rejects_toml_spelling_as_override_key():
    """overrides is keyed by field name, so the TOML spelling is invalid."""
    with pytest.raises(ScrubberError, match='clear-text'):
        FileEntry(
            input=Path('a.ipynb'),
            output=Path('b.ipynb'),
            overrides={'clear-text': 'x'},
        )


def test_direct_construction_with_valid_overrides_merges():
    entry = FileEntry(
        input=Path('a.ipynb'),
        output=Path('b.ipynb'),
        overrides={'clear_text': '', 'clear_tag': 'mine'},
    )
    merged = entry.get_options(
        ScrubbingOptions(clear_text='GLOBAL', clear_tag='theirs', omit_tag='keep'),
    )
    assert merged.clear_text == ''
    assert merged.clear_tag == 'mine'
    assert merged.omit_tag == 'keep'


def test_direct_construction_without_overrides_is_valid():
    entry = FileEntry(input=Path('a.ipynb'), output=Path('b.ipynb'))
    assert entry.overrides == {}
    assert entry.get_options(ScrubbingOptions(clear_tag='G')).clear_tag == 'G'


def test_override_error_is_distinct_from_toml_key_error():
    """Each layer names itself so a reader knows which one rejected."""
    with pytest.raises(ScrubberError) as from_dict_err:
        FileEntry.from_dict(
            {'input': 'a.ipynb', 'output': 'b.ipynb', 'clear_text': 'x'},
        )
    with pytest.raises(ScrubberError) as post_init_err:
        FileEntry(
            input=Path('a.ipynb'),
            output=Path('b.ipynb'),
            overrides={'clear-text': 'x'},
        )

    assert 'file entry key' in str(from_dict_err.value)
    assert 'file entry override' in str(post_init_err.value)
