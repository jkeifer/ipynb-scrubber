from __future__ import annotations

import tomllib

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from .exceptions import ScrubberError


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create GlobalOptions from dictionary."""
        return cls(
            clear_tag=data.get('clear-tag', 'scrub-clear'),
            clear_text=data.get('clear-text', '# TODO: Implement this'),
            omit_tag=data.get('omit-tag', 'scrub-omit'),
        )


@dataclass
class FileEntry:
    """Configuration for a single notebook file."""

    input: Path
    output: Path
    clear_tag: str | None = None
    clear_text: str | None = None
    omit_tag: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create FileEntry from dictionary."""
        if 'input' not in data:
            raise ScrubberError('File entry missing required field: input')
        if 'output' not in data:
            raise ScrubberError('File entry missing required field: output')

        return cls(
            input=Path(data['input']),
            output=Path(data['output']),
            clear_tag=data.get('clear-tag'),
            clear_text=data.get('clear-text'),
            omit_tag=data.get('omit-tag'),
        )

    def get_options(self, global_options: ScrubbingOptions) -> ScrubbingOptions:
        """Get merged options for this file (file-specific overrides global)."""
        return ScrubbingOptions(
            clear_tag=self.clear_tag or global_options.clear_tag,
            clear_text=self.clear_text or global_options.clear_text,
            omit_tag=self.omit_tag or global_options.omit_tag,
        )


@dataclass
class ProjectConfig:
    """Configuration for scrubbing a project."""

    global_options: ScrubbingOptions = field(default_factory=ScrubbingOptions)
    files: list[FileEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create ProjectConfig from dictionary."""
        global_options = ScrubbingOptions.from_dict(
            data.get('options', {}),
        )

        files_data = data.get('files', [])
        if not files_data:
            raise ScrubberError('Config file must contain at least one file entry')

        files = [FileEntry.from_dict(f) for f in files_data]

        return cls(global_options=global_options, files=files)

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
