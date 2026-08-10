import argparse
import json
import sys

from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar, NoReturn, Protocol

from .config import ProjectConfig, ScrubbingOptions
from .exceptions import ScrubberError
from .notebook import dumps_notebook, get_notebook_language, loads_notebook
from .notes import render_notes, require_destination
from .processor import process_notebook
from .project import scrub_files
from .staging import write_atomic

_DEFAULTS = ScrubbingOptions()


def printe(*args: object, **kwargs: Any) -> None:
    print(*args, file=sys.stderr, **kwargs)  # noqa: T201


class Command(Protocol):
    help: ClassVar[str] = ''

    @property
    def name(self) -> str: ...

    def set_args(self, parser: argparse.ArgumentParser) -> None: ...

    def __call__(self, args: argparse.Namespace) -> int: ...


class CLI:
    def __init__(
        self,
        *commands: Command,
        prog: str | None = None,
        description: str | None = None,
    ) -> None:
        self.parser = argparse.ArgumentParser(
            prog=prog,
            description=description,
            formatter_class=argparse.RawTextHelpFormatter,
        )
        self._subparsers = self.parser.add_subparsers(
            title='commands',
            dest='command',
        )
        self._subparsers.metavar = '[command]'

        for command in commands:
            self.add_command(command)

    def add_command(self, command: Command) -> None:
        parser = self._subparsers.add_parser(
            command.name,
            help=command.help,
        )
        command.set_args(parser)
        parser.set_defaults(_cmd=command)

    def _process_args(
        self,
        argv: Sequence[str] | None = None,
    ) -> argparse.Namespace:
        args: argparse.Namespace = self.parser.parse_args(argv)

        if args.command is None:
            printe('error: command required')
            self.parser.print_help()
            sys.exit(2)

        return args

    def __call__(self, argv: Sequence[str] | None = None) -> NoReturn:
        args = self._process_args(argv)
        sys.exit(args._cmd(args))


class ScrubNotebook:
    help: ClassVar[str] = (
        'Reads a Jupyter notebook from stdin, '
        'processes it to clear cell outputs, '
        'and writes the exercise version to stdout. '
        'Cells tagged with the omit tag are omitted '
        'from the exercise version, while those tagged '
        'with the clear tag are cleared and a message '
        'is added to indicate they are to be completed '
        'by the user.'
    )
    name = 'scrub-notebook'

    def set_args(self, parser: argparse.ArgumentParser) -> None:
        for key, spec in ScrubbingOptions.KEYS.items():
            parser.add_argument(
                f'--{key}',
                dest=spec.field,
                default=getattr(_DEFAULTS, spec.field),
                help=spec.help,
            )
        parser.add_argument(
            '--notes-file',
            type=Path,
            default=None,
            help=(
                'Path to write notes file (required if any cell carries the note tag)'
            ),
        )

    def __call__(self, args: argparse.Namespace) -> int:
        try:
            try:
                # Read the raw bytes: a notebook's encoding is a property of
                # the notebook, not of the locale the tool happens to run in.
                notebook = loads_notebook(sys.stdin.buffer.read())
            except json.JSONDecodeError as e:
                raise ScrubberError(f'Invalid JSON input: {e}') from e
            except (OSError, UnicodeDecodeError) as e:
                # A mis-encoded byte on stdin is bad input like any other, so
                # it earns the friendly contract rather than a traceback.
                raise ScrubberError(f'Error reading input: {e}') from e

            options = ScrubbingOptions(
                **{
                    spec.field: getattr(args, spec.field)
                    for spec in ScrubbingOptions.KEYS.values()
                },
            )

            processed_notebook, notes_dict = process_notebook(notebook, options)

            require_destination(
                notes_dict,
                args.notes_file,
                options.note_tag,
                'Pass --notes-file PATH.',
            )

            if notes_dict:
                try:
                    write_atomic(
                        args.notes_file,
                        render_notes(
                            notes_dict,
                            get_notebook_language(processed_notebook),
                        ),
                    )
                except OSError as e:
                    raise ScrubberError(f'Error writing notes file: {e}') from e

            try:
                # Bytes again, for the same reason as stdin: the output encoding
                # belongs to the notebook, not to the terminal it is piped into.
                sys.stdout.buffer.write(
                    dumps_notebook(processed_notebook).encode('utf-8'),
                )
                sys.stdout.buffer.flush()
            except OSError as e:
                raise ScrubberError(f'Error writing output: {e}') from e

        except ScrubberError as e:
            printe(f'Error: {e}')
            return 1
        return 0


class ScrubProject:
    help: ClassVar[str] = (
        'Executes notebook scrubbing using project configuration. '
        'Searches for .ipynb-scrubber.toml or pyproject.toml with '
        '[tool.ipynb-scrubber] section. The configured files are written '
        'as a batch: if any one of them fails, none are written.'
    )
    name = 'scrub-project'

    def set_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            '--config-file',
            default=None,
            type=Path,
            help=(
                'Path to config file (default: searches for .ipynb-scrubber.toml '
                'or pyproject.toml with [tool.ipynb-scrubber] section)'
            ),
        )

    def __call__(self, args: argparse.Namespace) -> int:
        try:
            if args.config_file is None:
                config = ProjectConfig.discover()
            else:
                config = ProjectConfig.from_file(args.config_file)
        except ScrubberError as e:
            printe(f'Error: {e}')
            return 1

        try:
            scrub_files(config.files)
        except ScrubberError as e:
            printe(f'✗ {e}')
            return 1

        # Reported only once the batch is committed, which is the moment each
        # of these lines becomes true.
        for file_entry in config.files:
            printe(f'✓ Processed: {file_entry.input} → {file_entry.output}')

        return 0


def _cli() -> CLI:
    return CLI(
        ScrubNotebook(),
        ScrubProject(),
        description='Scrub notebooks to create exercise versions',
    )


def cli() -> None:
    _cli()()


if __name__ == '__main__':
    cli()
