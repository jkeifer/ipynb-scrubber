from __future__ import annotations

import re
import tomllib

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar, Self

import yaml

from .exceptions import ScrubberError

#: What an option name may look like. A name is written as a YAML key in a
#: cell's option header, so it has to survive that round trip as itself, and
#: this is half of that: no leading indicator character, no whitespace, nothing
#: YAML would have to quote to carry as a bare key.
TAG_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]*')

#: The other half: what YAML tags a scalar it reads as text, and so what a name
#: has to come back tagged to arrive off a header as the name it was written
#: as. Asked of YAML's own resolver rather than checked against a list of words
#: kept here, so the answer stays the one PyYAML gives when it reads a header.
_STRING_TAG = 'tag:yaml.org,2002:str'


def reject_unknown_keys(
    data: dict[str, Any],
    valid: Collection[str],
    label: str,
) -> None:
    """Raise if ``data`` carries a key outside ``valid``.

    Config keys are a closed, enumerable set, so a typo is always a mistake
    rather than a forward-compatible extension. Silently dropping one is
    especially bad here: a misspelled ``clear-tag`` means solution cells are
    not scrubbed at all.

    Raises:
        ScrubberError: If any key is unrecognised.
    """
    unknown = sorted(set(data) - set(valid))
    if unknown:
        raise ScrubberError(
            f'Unknown {label}(s): {", ".join(unknown)}. '
            f'Valid {label}s: {", ".join(sorted(valid))}',
        )


def reject_wrong_type(key: str, value: Any, expected: type) -> None:
    """Raise unless ``value`` is the type ``key`` is declared to hold.

    TOML values arrive untyped and are handed straight to a dataclass, so a
    wrong type is otherwise found only by whatever eventually chokes on it:
    a traceback from a regex handed an int, or — worse, because nothing
    complains — a notebook written out with a number where its source should
    be.

    Raises:
        ScrubberError: If ``value`` is not an instance of ``expected``.
    """
    if not isinstance(value, expected):
        raise ScrubberError(
            f'{key} must be {expected.__name__}, but got '
            f'{type(value).__name__}: {value!r}',
        )


def _load_scrubber_section(path: Path) -> dict[str, Any] | None:
    """Read ``path`` and return the scrubber configuration it defines.

    A ``pyproject.toml`` carries its configuration under
    ``[tool.ipynb-scrubber]``; any other file is a standalone config and is
    its configuration in its entirety.

    Returns:
        The configuration mapping, or None for a ``pyproject.toml`` with no
        ``[tool.ipynb-scrubber]`` section.

    Raises:
        ScrubberError: If the file cannot be read or parsed as TOML.
    """
    try:
        with path.open('rb') as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ScrubberError(f'Invalid TOML in {path}: {e}') from e
    except OSError as e:
        raise ScrubberError(f'Error reading {path}: {e}') from e

    if path.name != 'pyproject.toml':
        return data

    section = data.get('tool', {}).get('ipynb-scrubber')
    return section if isinstance(section, dict) else None


def find_config(start_dir: Path | None = None) -> tuple[Path, dict[str, Any]] | None:
    """Search upward from start_dir for a config file and load it.

    Searches for .ipynb-scrubber.toml or pyproject.toml with
    [tool.ipynb-scrubber], from start_dir up to the filesystem root. The
    file is parsed as part of the search, so callers need not re-read it.

    Args:
        start_dir: Directory to start searching from (default: cwd)

    Returns:
        The config file's path and its configuration mapping, or None if no
        config file was found.

    Raises:
        ScrubberError: If a candidate config file cannot be read or parsed.
    """
    current = (Path.cwd() if start_dir is None else start_dir).resolve()

    while True:
        standalone_config = current / '.ipynb-scrubber.toml'
        if standalone_config.exists():
            # Not a pyproject.toml, so the file is the config in full and
            # _load_scrubber_section never reports a missing section.
            return standalone_config, _load_scrubber_section(standalone_config) or {}

        pyproject = current / 'pyproject.toml'
        if pyproject.exists():
            try:
                section = _load_scrubber_section(pyproject)
            except ScrubberError as e:
                # A pyproject.toml we can't read or parse makes the search
                # unsound: we cannot tell whether it would have carried a
                # [tool.ipynb-scrubber] section, so neither "use this other
                # config" nor "no config found" can be trusted. Fail loudly
                # instead of silently searching past it.
                raise ScrubberError(
                    f'{e}. Fix or remove this file so config discovery can '
                    'determine whether it defines [tool.ipynb-scrubber].',
                ) from e
            if section is not None:
                return pyproject, section

        parent = current.parent
        if parent == current:
            return None
        current = parent


@dataclass(frozen=True)
class OptionSpec:
    """Everything the rest of the code needs to know about one option.

    The config loader, the value-type check and the CLI flag all read the
    same entry, so an option exists in exactly one place instead of having to
    be kept in agreement across several.
    """

    field: str
    type: type
    help: str


@dataclass
class ScrubbingOptions:
    """Scrubbing options."""

    clear_tag: str = 'scrub-clear'
    clear_text: str = '# TODO: Implement this'
    clear_text_markdown: str = '*TODO: Implement this*'
    omit_tag: str = 'scrub-omit'
    note_tag: str = 'scrub-note'

    #: TOML key -> the option it names. The single source of truth for which
    #: options exist, what they are called in config files, what a value for
    #: one has to be, and how each describes itself on the command line.
    KEYS: ClassVar[dict[str, OptionSpec]] = {
        'clear-tag': OptionSpec(
            'clear_tag',
            str,
            'Tag marking cells to clear',
        ),
        'clear-text': OptionSpec(
            'clear_text',
            str,
            'Text for cleared cells where unspecified',
        ),
        'clear-text-markdown': OptionSpec(
            'clear_text_markdown',
            str,
            'Text for cleared markdown cells where unspecified',
        ),
        'omit-tag': OptionSpec(
            'omit_tag',
            str,
            'Tag marking cells to omit entirely',
        ),
        'note-tag': OptionSpec(
            'note_tag',
            str,
            'Option name marking cells to save to notes',
        ),
    }

    def __post_init__(self) -> None:
        """Reject values of the wrong type, and tag names unusable or colliding.

        The type check comes first so the two name checks below only ever see
        strings: a config file can put anything at all under a key, and a
        regex handed an int raises something the CLI does not know how to
        report.

        A tag is written as a YAML key in a cell's option header and as a
        metadata tag, so it has to be something YAML reads back as the same
        plain string and a reader can pick out of a comment. The pattern is
        not enough for that on its own: YAML reads a handful of plain words as
        another type — ``yes`` and ``no`` are booleans, ``null`` is nothing at
        all — in any capitalisation its resolver accepts, so a tag spelled as
        one is written into a header where an option goes but arrives as a
        bool or None. Nothing looking the option up by name would find it and
        the cell would ship unscrubbed without a word; for ``omit-tag`` that
        means shipping the solution. Settling both here is what lets
        everything downstream take a configured name at its word.

        The three tags are also matched as a set, so two spellings that are
        equal collapse into one and whichever behaviour loses the precedence
        order silently disappears. All of it runs for ``replace()`` too, so a
        per-file override that breaks any rule is caught as well.

        Raises:
            ScrubberError: If a value is not the declared type, if a tag is
                not a usable name, or if the three tags are not all distinct.
        """
        for key, spec in self.KEYS.items():
            reject_wrong_type(key, getattr(self, spec.field), spec.type)

        named = {
            'clear-tag': self.clear_tag,
            'omit-tag': self.omit_tag,
            'note-tag': self.note_tag,
        }

        resolve = yaml.resolver.Resolver().resolve
        for key, name in named.items():
            if not TAG_NAME.fullmatch(name):
                raise ScrubberError(
                    f'{key} must start with a letter and contain only letters, '
                    f'digits, hyphens and underscores, but got {name!r}',
                )
            if resolve(yaml.ScalarNode, name, (True, False)) != _STRING_TAG:
                raise ScrubberError(
                    f'{key} must be a name YAML reads back as text, but got '
                    f'{name!r}, which YAML resolves to another type. Words like '
                    'yes, no, on, off, true, false and null are not names',
                )

        tags = tuple(named.values())
        if len(set(tags)) != len(tags):
            raise ScrubberError(
                'clear-tag, omit-tag and note-tag must all be distinct, but '
                f'got clear-tag={self.clear_tag!r}, omit-tag={self.omit_tag!r}, '
                f'note-tag={self.note_tag!r}',
            )

    def merged_with(self, data: dict[str, Any]) -> Self:
        """Return a copy with every option ``data`` mentions overridden.

        Presence-based, not truthiness-based: a key that is present is used
        verbatim, including an empty string. Keys absent from ``data`` keep
        this instance's value.

        Raises:
            ScrubberError: If an override is not the declared type, or if the
                merged tags are not all distinct.
        """
        return replace(
            self,
            **{spec.field: data[key] for key, spec in self.KEYS.items() if key in data},
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create ScrubbingOptions from a config mapping.

        Raises:
            ScrubberError: If ``data`` contains an unrecognised key, a value
                of the wrong type, or tags that are not all distinct.
        """
        reject_unknown_keys(data, cls.KEYS, 'option')
        return cls().merged_with(data)


@dataclass
class FileEntry:
    """One notebook to scrub, with the options resolved for it."""

    input: Path
    output: Path
    options: ScrubbingOptions = field(default_factory=ScrubbingOptions)
    notes_file: Path | None = None

    #: TOML keys a file entry accepts beyond the ScrubbingOptions keys, and
    #: the type each value has to be. All three name a path, and a path is
    #: something TOML can only spell as a string.
    OWN_KEYS: ClassVar[dict[str, type]] = {
        'input': str,
        'output': str,
        'notes-file': str,
    }

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: ScrubbingOptions) -> Self:
        """Create FileEntry from a config mapping.

        Options the entry does not mention are inherited from ``defaults``.

        Raises:
            ScrubberError: If input or output is missing, a key is
                unrecognised, a value is not the declared type, notes-file is
                empty, or the resolved tags are not all distinct.
        """
        reject_unknown_keys(
            data,
            cls.OWN_KEYS.keys() | ScrubbingOptions.KEYS.keys(),
            'file entry key',
        )
        for key, expected in cls.OWN_KEYS.items():
            if key in data:
                reject_wrong_type(key, data[key], expected)

        if 'input' not in data:
            raise ScrubberError('File entry missing required field: input')
        if 'output' not in data:
            raise ScrubberError('File entry missing required field: output')

        # Presence, not truthiness, like every other key here. That leaves
        # nowhere for an empty notes-file to mean "no notes file": it is a
        # path that was asked for and cannot be written, so it is an error.
        notes_file = None
        if 'notes-file' in data:
            if not data['notes-file']:
                raise ScrubberError(
                    'notes-file must not be empty; omit the key entirely for '
                    'no notes file',
                )
            notes_file = Path(data['notes-file'])

        return cls(
            input=Path(data['input']),
            output=Path(data['output']),
            options=defaults.merged_with(data),
            notes_file=notes_file,
        )


@dataclass
class ProjectConfig:
    """Configuration for scrubbing a project."""

    files: list[FileEntry] = field(default_factory=list)

    TOP_LEVEL_KEYS: ClassVar[frozenset[str]] = frozenset({'options', 'files'})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create ProjectConfig from dictionary.

        Raises:
            ScrubberError: If a key is unrecognised or no file entries exist.
        """
        reject_unknown_keys(data, cls.TOP_LEVEL_KEYS, 'config key')

        defaults = ScrubbingOptions.from_dict(data.get('options', {}))

        files_data = data.get('files', [])
        if not files_data:
            raise ScrubberError('Config file must contain at least one file entry')

        return cls(files=[FileEntry.from_dict(f, defaults) for f in files_data])

    @classmethod
    def from_file(cls, config_path: Path) -> Self:
        """Load configuration from a TOML file.

        Supports both standalone .ipynb-scrubber.toml files and
        pyproject.toml files with [tool.ipynb-scrubber] section.

        Args:
            config_path: Path to config file

        Returns:
            ProjectConfig instance

        Raises:
            ScrubberError: If file not found, invalid TOML, or missing config
        """
        if not config_path.exists():
            raise ScrubberError(f'Config file not found: {config_path}')

        data = _load_scrubber_section(config_path)
        if data is None:
            raise ScrubberError(
                f'{config_path} does not contain [tool.ipynb-scrubber] section',
            )

        return cls.from_dict(data)

    @classmethod
    def discover(cls, start_dir: Path | None = None) -> Self:
        """Discover and load configuration by searching upward from start_dir.

        Searches for .ipynb-scrubber.toml or pyproject.toml with
        [tool.ipynb-scrubber] section, starting from start_dir and moving
        upward to filesystem root.

        Args:
            start_dir: Directory to start searching from (default: cwd)

        Returns:
            ProjectConfig instance

        Raises:
            ScrubberError: If no config file found
        """
        found = find_config(start_dir)
        if found is None:
            raise ScrubberError(
                'No config file found. Expected .ipynb-scrubber.toml or '
                'pyproject.toml with [tool.ipynb-scrubber] section',
            )
        _, data = found
        return cls.from_dict(data)
