from __future__ import annotations

import re
import tomllib

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar, Self

from .exceptions import ScrubberError

#: What an option name may look like. A name is written as a YAML key in a
#: cell's option header, so it has to survive that round trip as itself: no
#: leading indicator character, no whitespace, nothing YAML would quote or
#: resolve to another type.
TAG_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]*')


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


@dataclass
class ScrubbingOptions:
    """Scrubbing options."""

    clear_tag: str = 'scrub-clear'
    clear_text: str = '# TODO: Implement this'
    omit_tag: str = 'scrub-omit'
    note_tag: str = 'scrub-note'

    #: TOML key -> dataclass field name. The single source of truth for
    #: which options exist and what they are called in config files.
    KEYS: ClassVar[dict[str, str]] = {
        'clear-tag': 'clear_tag',
        'clear-text': 'clear_text',
        'omit-tag': 'omit_tag',
        'note-tag': 'note_tag',
    }

    def __post_init__(self) -> None:
        """Reject tag names that are unusable or that collide.

        A tag is written as a YAML key in a cell's option header and as a
        metadata tag, so it has to be something YAML reads back as the same
        plain string and a reader can pick out of a comment.

        The three tags are also matched as a set, so two spellings that are
        equal collapse into one and whichever behaviour loses the precedence
        order silently disappears. Both checks run for ``replace()`` too, so a
        per-file override that breaks either rule is caught as well.

        Raises:
            ScrubberError: If a tag is not a usable name, or if the three are
                not all distinct.
        """
        named = {
            'clear-tag': self.clear_tag,
            'omit-tag': self.omit_tag,
            'note-tag': self.note_tag,
        }

        for key, name in named.items():
            if not TAG_NAME.fullmatch(name):
                raise ScrubberError(
                    f'{key} must start with a letter and contain only letters, '
                    f'digits, hyphens and underscores, but got {name!r}',
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
            ScrubberError: If the merged tags are not all distinct.
        """
        return replace(
            self,
            **{field: data[key] for key, field in self.KEYS.items() if key in data},
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create ScrubbingOptions from a config mapping.

        Raises:
            ScrubberError: If ``data`` contains an unrecognised key or the
                resulting tags are not all distinct.
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

    #: TOML keys a file entry accepts beyond the ScrubbingOptions keys.
    OWN_KEYS: ClassVar[frozenset[str]] = frozenset(
        {'input', 'output', 'notes-file'},
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: ScrubbingOptions) -> Self:
        """Create FileEntry from a config mapping.

        Options the entry does not mention are inherited from ``defaults``.

        Raises:
            ScrubberError: If input or output is missing, a key is
                unrecognised, or the resolved tags are not all distinct.
        """
        reject_unknown_keys(
            data,
            cls.OWN_KEYS | ScrubbingOptions.KEYS.keys(),
            'file entry key',
        )
        if 'input' not in data:
            raise ScrubberError('File entry missing required field: input')
        if 'output' not in data:
            raise ScrubberError('File entry missing required field: output')

        notes_file = data.get('notes-file')
        return cls(
            input=Path(data['input']),
            output=Path(data['output']),
            options=defaults.merged_with(data),
            notes_file=Path(notes_file) if notes_file else None,
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
