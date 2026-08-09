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
