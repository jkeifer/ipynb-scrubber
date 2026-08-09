from __future__ import annotations

import tomllib

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar, Self

from .exceptions import ScrubberError


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


def find_config_file(start_dir: Path | None = None) -> Path | None:
    """Search upward from start_dir for a config file.

    Searches for .ipynb-scrubber.toml or pyproject.toml with [tool.ipynb-scrubber].
    Searches from start_dir upward to filesystem root.

    Args:
        start_dir: Directory to start searching from (default: cwd)

    Returns:
        Path to config file, or None if not found
    """
    if start_dir is None:
        start_dir = Path.cwd()

    current = start_dir.resolve()

    # Search upward until we hit the filesystem root
    while True:
        # Check for standalone config file first
        standalone_config = current / '.ipynb-scrubber.toml'
        if standalone_config.exists():
            return standalone_config

        # Check for pyproject.toml with [tool.ipynb-scrubber] section
        pyproject = current / 'pyproject.toml'
        if pyproject.exists():
            try:
                with pyproject.open('rb') as f:
                    data = tomllib.load(f)
                # Check if it has our config section
                if 'tool' in data and 'ipynb-scrubber' in data['tool']:
                    return pyproject
            except Exception:  # noqa: BLE001, S110
                # Invalid TOML or read error, skip this file
                pass

        # Move up one directory
        parent = current.parent
        if parent == current:
            # We've reached the filesystem root
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create ScrubbingOptions from a config mapping.

        Keys absent from ``data`` keep their dataclass default; a key that
        is present is used verbatim, including an empty string.

        Raises:
            ScrubberError: If ``data`` contains an unrecognised key.
        """
        reject_unknown_keys(data, cls.KEYS, 'option')
        return cls(
            **{field: data[key] for key, field in cls.KEYS.items() if key in data},
        )


@dataclass
class FileEntry:
    """Configuration for a single notebook file."""

    input: Path
    output: Path
    notes_file: Path | None = None
    overrides: dict[str, Any] = field(default_factory=dict)

    #: TOML keys a file entry accepts beyond the ScrubbingOptions keys.
    OWN_KEYS: ClassVar[frozenset[str]] = frozenset(
        {'input', 'output', 'notes-file'},
    )

    def __post_init__(self) -> None:
        """Enforce that ``overrides`` is keyed by ScrubbingOptions field names.

        ``from_dict`` is the normal construction path and always satisfies
        this, but the invariant is what makes ``get_options`` safe. Checking
        it here means a direct construction with a bad key fails immediately
        with a clear error, rather than a ``TypeError`` raised from inside
        ``dataclasses.replace`` at merge time.

        Raises:
            ScrubberError: If an override is not a ScrubbingOptions field.
        """
        reject_unknown_keys(
            self.overrides,
            set(ScrubbingOptions.KEYS.values()),
            'file entry override',
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create FileEntry from dictionary.

        Raises:
            ScrubberError: If input or output is missing, or a key is
                unrecognised.
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
            notes_file=Path(notes_file) if notes_file else None,
            overrides={
                field_name: data[key]
                for key, field_name in ScrubbingOptions.KEYS.items()
                if key in data
            },
        )

    def get_options(self, global_options: ScrubbingOptions) -> ScrubbingOptions:
        """Merge this file's overrides over the global options.

        Presence-based, not truthiness-based: a file that explicitly sets
        ``clear-text = ""`` gets an empty string, not the global default.
        """
        return replace(global_options, **self.overrides)


@dataclass
class ProjectConfig:
    """Configuration for scrubbing a project."""

    global_options: ScrubbingOptions = field(default_factory=ScrubbingOptions)
    files: list[FileEntry] = field(default_factory=list)

    TOP_LEVEL_KEYS: ClassVar[frozenset[str]] = frozenset({'options', 'files'})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create ProjectConfig from dictionary.

        Raises:
            ScrubberError: If a key is unrecognised or no file entries exist.
        """
        reject_unknown_keys(data, cls.TOP_LEVEL_KEYS, 'config key')

        global_options = ScrubbingOptions.from_dict(data.get('options', {}))

        files_data = data.get('files', [])
        if not files_data:
            raise ScrubberError('Config file must contain at least one file entry')

        return cls(
            global_options=global_options,
            files=[FileEntry.from_dict(f) for f in files_data],
        )

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

        try:
            with config_path.open('rb') as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ScrubberError(f'Invalid TOML in config file: {e}') from e
        except Exception as e:
            raise ScrubberError(f'Error reading config file: {e}') from e

        # If this is a pyproject.toml, extract the tool.ipynb-scrubber section
        if config_path.name == 'pyproject.toml':
            if 'tool' not in data or 'ipynb-scrubber' not in data['tool']:
                raise ScrubberError(
                    f'{config_path} does not contain [tool.ipynb-scrubber] section',
                )
            data = data['tool']['ipynb-scrubber']

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
        config_path = find_config_file(start_dir)
        if config_path is None:
            raise ScrubberError(
                'No config file found. Expected .ipynb-scrubber.toml or '
                'pyproject.toml with [tool.ipynb-scrubber] section',
            )
        return cls.from_file(config_path)
