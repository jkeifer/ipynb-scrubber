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

    ``takes_text`` carries the one thing about an option that is only true once
    it leaves a config file. An option whose value names a tag is written again
    inside a notebook, where its own value is either text the author wrote or
    nothing at all, and that is the one fact the header parser needs beyond the
    name. ``None`` says the option names no tag at all: ``clear-text`` says
    what a cleared cell is left holding, it does not mark a cell. Carrying it
    here is what makes this registry the answer to "which options are tags",
    instead of a second list kept beside it and forgotten.
    """

    field: str
    type: type
    help: str
    takes_text: bool | None = None


@dataclass(frozen=True)
class TagSpec:
    """One option that marks cells, as the code that reads cells needs it.

    A tag's spelling is configured, so what is fixed is the field holding it
    rather than the name itself: a caller resolves ``field`` against the
    options it was handed. ``takes_text`` is not optional here, because
    everything in this projection of the registry is a tag — which is the point
    of the projection.
    """

    field: str
    takes_text: bool


@dataclass(frozen=True)
class ScrubbingOptions:
    """Scrubbing options.

    Frozen because every rule this class enforces lives in ``__post_init__``,
    and a settable field is a way around all of them at once. Nothing checks a
    tag name again after construction, so ``opts.omit_tag = 'no'`` would leave
    an instance holding a name the constructor exists to reject — the option
    written into a header and read back as a bool, under a key no lookup by
    name finds, which for ``omit-tag`` means shipping the solution. A rule a
    single assignment walks past is not enforcing anything.

    To derive a modified copy, use ``merged_with`` or ``dataclasses.replace``:
    both build a new instance, so both are checked exactly as construction is.
    """

    clear_tag: str = 'scrub-clear'
    clear_text: str = '# TODO: Implement this'
    clear_text_markdown: str = '*TODO: Implement this*'
    omit_tag: str = 'scrub-omit'
    note_tag: str = 'scrub-note'

    #: TOML key -> the option it names. The single source of truth for which
    #: options exist, what they are called in config files, what a value for
    #: one has to be, how each describes itself on the command line, and which
    #: of them go on to mark cells.
    KEYS: ClassVar[dict[str, OptionSpec]] = {
        'clear-tag': OptionSpec(
            'clear_tag',
            str,
            'Tag marking cells to clear',
            takes_text=True,
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
            takes_text=False,
        ),
        'note-tag': OptionSpec(
            'note_tag',
            str,
            'Option name marking cells to save to notes',
            takes_text=True,
        ),
    }

    @classmethod
    def tags(cls) -> dict[str, TagSpec]:
        """The options that name a tag, by the config key naming each.

        Derived from the registry rather than listed again, so a tag added
        there is a tag everywhere at once: the name checks below, the header
        parser that has to know whose values it is reading, and the precedence
        order that decides what a cell carrying one becomes. A tag the registry
        knows and one of those layers does not is silent breakage — the option
        is written, and then nothing at all happens to the cell.
        """
        return {
            key: TagSpec(spec.field, spec.takes_text)
            for key, spec in cls.KEYS.items()
            if spec.takes_text is not None
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

        The tags are also matched as a set, so two spellings that are equal
        collapse into one and whichever behaviour loses the precedence order
        silently disappears. All of it runs for ``replace()`` too, so a
        per-file override that breaks any rule is caught as well.

        Which options are tags is asked of the registry, so a tag added there
        is checked here without anyone having to remember to add it: an
        unchecked name is one every rule above was written to catch.

        Raises:
            ScrubberError: If a value is not the declared type, if a tag is
                not a usable name, or if the tags are not all distinct.
        """
        for key, spec in self.KEYS.items():
            reject_wrong_type(key, getattr(self, spec.field), spec.type)

        named = {key: getattr(self, tag.field) for key, tag in self.tags().items()}

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
            keys = ', '.join(named)
            spellings = ', '.join(f'{key}={name!r}' for key, name in named.items())
            raise ScrubberError(
                f'{keys} must all be distinct, but got {spellings}',
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

    def __post_init__(self) -> None:
        """Reject an entry that would write over one of its own paths.

        This tool derives an exercise copy, and the source it derives from has
        to still be there afterwards. Nothing downstream is in a position to
        notice otherwise: scrubbing reads the input, stages the output, and
        renames it into place, so an entry naming one path twice is a run that
        finishes, reports the file as processed, and leaves the source holding
        its own scrubbed copy with every solution gone. Outside version
        control there is nothing to recover it from.

        Here rather than in ``from_dict`` because it is a fact about the paths
        an entry holds, not about the mapping one was read from: a caller
        building an entry by hand gets the same guarantee a config file does,
        which is the point of checking it at all.

        Paths are compared as written, without resolving them. That catches
        the mistake people actually make — the same path twice, or an output
        never repointed away from its input — and it catches it without
        touching the filesystem, which is not something a constructor should
        be doing. ``Path`` normalises a leading ``./`` on the way in, so
        ``./a.ipynb`` and ``a.ipynb`` are already the same path here. Two
        spellings that only meet once resolved — through ``..``, a symlink,
        or two different relative paths — are not caught, and are a mistake
        of a different and much rarer kind.

        Raises:
            ScrubberError: If any two of input, output and notes-file name the
                same path.
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
    def from_dict(cls, data: dict[str, Any], defaults: ScrubbingOptions) -> Self:
        """Create FileEntry from a config mapping.

        Options the entry does not mention are inherited from ``defaults``.

        Raises:
            ScrubberError: If input or output is missing, a key is
                unrecognised, a value is not the declared type, notes-file is
                empty, the resolved tags are not all distinct, or the entry's
                paths are not all distinct.
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

    def __post_init__(self) -> None:
        """Reject entries that write over each other's paths.

        An entry settles its own three paths, which is all it can see. Two
        entries writing the same file, or one writing over another's input,
        are the same destruction — a source notebook replaced by generated
        output, or an output replaced by another entry's — and are only
        visible with the whole batch in hand, which is what this class is.

        The batch being all-or-nothing does not soften this. Every output is
        staged before any is committed, so a collision is not an ordering
        hazard that might be caught: both writes are prepared, both are
        committed, the target ends up holding whichever landed last, and both
        entries are reported as processed. Nothing about the run says the
        first result was thrown away.

        Paths are compared as written, for the reasons ``FileEntry`` gives.

        Raises:
            ScrubberError: If two entries write the same path, or an entry
                writes over another entry's input.
        """
        # An entry colliding with itself never reaches here: FileEntry rejects
        # that, so every path recorded below belongs to exactly one entry.
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
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create ProjectConfig from dictionary.

        Raises:
            ScrubberError: If a key is unrecognised, no file entries exist, an
                entry is invalid, or two entries collide over a path.
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
