from __future__ import annotations

import tomllib

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Self

from .exceptions import ScrubberError
from .options import OPTIONS, ScrubbingOptions
from .validation import reject_unknown_keys, reject_wrong_type


def _load_scrubber_section(path: Path) -> dict[str, Any] | None:
    """Read the scrubber configuration ``path`` holds.

    A standalone config is read whole; a ``pyproject.toml`` yields its
    ``[tool.ipynb-scrubber]`` section, or None when that section is absent.

    Raises:
        ScrubberError: If the file cannot be read or parsed.
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
    """Search upward from start_dir (default cwd) for a config file.

    Returns the path and mapping of the first one found, or None.

    Raises:
        ScrubberError: If a candidate cannot be read or parsed.
    """
    current = (Path.cwd() if start_dir is None else start_dir).resolve()

    while True:
        standalone_config = current / '.ipynb-scrubber.toml'
        if standalone_config.exists():
            # Not a pyproject.toml, so there is no missing section to report.
            return standalone_config, _load_scrubber_section(standalone_config) or {}

        pyproject = current / 'pyproject.toml'
        if pyproject.exists():
            try:
                section = _load_scrubber_section(pyproject)
            except ScrubberError as e:
                # An unreadable pyproject.toml makes the search unsound: we
                # cannot tell whether it carried a [tool.ipynb-scrubber]
                # section, so neither "use this other config" nor "no config
                # found" is trustworthy. Fail rather than search past it.
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
class FileEntry:
    """One notebook to scrub, with the options resolved for it."""

    input: Path
    output: Path
    options: ScrubbingOptions = field(default_factory=ScrubbingOptions)
    notes_file: Path | None = None

    #: TOML keys a file entry accepts beyond the ScrubbingOptions keys. All
    #: three name a path, which TOML can only spell as a string.
    OWN_KEYS: ClassVar[dict[str, type]] = {
        'input': str,
        'output': str,
        'notes-file': str,
    }

    def __post_init__(self) -> None:
        """Reject an entry that would write over one of its own paths.

        Nothing downstream can notice: the run finishes, reports success, and
        leaves the source holding its own scrubbed copy with every solution
        gone, unrecoverable outside version control. Paths compare as written,
        so two spellings that meet only once resolved are not caught.

        Raises:
            ScrubberError: If any two of the entry's paths are the same.
        """
        if self.input == self.output:
            raise ScrubberError(
                f'input and output must name different files, but both are '
                f'{self.input}. The scrubbed notebook is written to output, so '
                'this would replace the source notebook with its own scrubbed '
                'copy and destroy the solutions in it.',
            )
        if self.notes_file == self.input:
            raise ScrubberError(
                f'notes-file and input must name different files, but both are '
                f'{self.input}. The notes are written to notes-file, so this '
                'would replace the source notebook with a notes file and '
                'destroy the solutions in it.',
            )
        if self.notes_file == self.output:
            raise ScrubberError(
                f'notes-file and output must name different files, but both '
                f'are {self.output}. Both are written, so one would silently '
                'overwrite the other and whichever landed last is all that '
                'would be left.',
            )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        defaults: ScrubbingOptions,
        base_dir: Path | None = None,
    ) -> Self:
        """Create FileEntry from a config mapping, inheriting from ``defaults``.

        A relative path is resolved against ``base_dir``, the directory the
        config was read from, so that what an entry names does not depend on
        where the command was run from. ``None`` means the working directory,
        for a mapping that came from no file at all.

        Raises:
            ScrubberError: On a missing input or output, an unknown key, a
                wrong-typed or empty value, or duplicate tags or paths.
        """
        base = Path.cwd() if base_dir is None else base_dir

        reject_unknown_keys(
            data,
            cls.OWN_KEYS.keys() | {option.key for option in OPTIONS},
            'file entry key',
        )
        for key, expected in cls.OWN_KEYS.items():
            if key in data:
                reject_wrong_type(key, data[key], expected)

        if 'input' not in data:
            raise ScrubberError('File entry missing required field: input')
        if 'output' not in data:
            raise ScrubberError('File entry missing required field: output')

        # Presence, not truthiness, like every other key, so an empty
        # notes-file is an unwritable path rather than "no notes file".
        notes_file = None
        if 'notes-file' in data:
            if not data['notes-file']:
                raise ScrubberError(
                    'notes-file must not be empty; omit the key entirely for '
                    'no notes file',
                )
            notes_file = base / data['notes-file']

        return cls(
            input=base / data['input'],
            output=base / data['output'],
            options=defaults.merged_with(data),
            notes_file=notes_file,
        )


@dataclass
class ProjectConfig:
    """Configuration for scrubbing a project."""

    files: list[FileEntry] = field(default_factory=list)

    TOP_LEVEL_KEYS: ClassVar[frozenset[str]] = frozenset({'options', 'files'})

    def __post_init__(self) -> None:
        """Reject entries that write over each other's paths.

        The batch being all-or-nothing does not help: both writes are staged
        and committed, and the target holds whichever landed last.

        Raises:
            ScrubberError: On two entries writing one path, or one writing over
                another's input.
        """
        # FileEntry rejects an entry colliding with itself, so every path
        # recorded below belongs to exactly one entry.
        writers: dict[Path, str] = {}
        for index, entry in enumerate(self.files):
            writes = [('output', entry.output)]
            if entry.notes_file is not None:
                writes.append(('notes-file', entry.notes_file))
            for key, path in writes:
                origin = f'files[{index}].{key}'
                if path in writers:
                    raise ScrubberError(
                        f'{writers[path]} and {origin} both write {path}. The '
                        'batch commits both, so one would silently overwrite '
                        'the other and whichever landed last is all that would '
                        'be left.',
                    )
                writers[path] = origin

        for index, entry in enumerate(self.files):
            writer = writers.get(entry.input)
            if writer is not None:
                raise ScrubberError(
                    f'{writer} writes {entry.input}, which is '
                    f'files[{index}].input. That would replace a source '
                    'notebook with generated output and destroy the solutions '
                    'in it.',
                )

    @classmethod
    def from_dict(cls, data: dict[str, Any], base_dir: Path | None = None) -> Self:
        """Create ProjectConfig from dictionary.

        ``base_dir`` is the directory each entry's relative paths are resolved
        against; ``None`` means the working directory.

        Raises:
            ScrubberError: On an unknown key, a section of the wrong shape, no
                file entries, an invalid entry, or a path collision.
        """
        reject_unknown_keys(data, cls.TOP_LEVEL_KEYS, 'config key')

        # Shape before content: both sections are handed to code that iterates
        # them, and a TOML file can spell either as anything at all. Checked
        # here so a number where a table belongs is reported against the key
        # holding it, rather than surfacing as whatever chokes on it first.
        options_data = data.get('options', {})
        reject_wrong_type('options', options_data, dict)
        defaults = ScrubbingOptions.from_dict(options_data)

        files_data = data.get('files', [])
        reject_wrong_type('files', files_data, list)
        if not files_data:
            raise ScrubberError('Config file must contain at least one file entry')
        for index, entry in enumerate(files_data):
            reject_wrong_type(f'files[{index}]', entry, dict)

        return cls(
            files=[
                FileEntry.from_dict(entry, defaults, base_dir) for entry in files_data
            ],
        )

    @classmethod
    def from_file(cls, config_path: Path) -> Self:
        """Load configuration from a standalone config or a pyproject.toml.

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

        return cls.from_dict(data, config_path.parent)

    @classmethod
    def discover(cls, start_dir: Path | None = None) -> Self:
        """Discover and load configuration by searching upward from start_dir.

        Entries are resolved against the directory the config was found in,
        which is what lets the search start anywhere: the run names the same
        files from a subdirectory as from the project root.

        Raises:
            ScrubberError: If no config file found
        """
        found = find_config(start_dir)
        if found is None:
            raise ScrubberError(
                'No config file found. Expected .ipynb-scrubber.toml or '
                'pyproject.toml with [tool.ipynb-scrubber] section',
            )
        config_path, data = found
        return cls.from_dict(data, config_path.parent)
