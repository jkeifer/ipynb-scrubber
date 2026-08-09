import argparse
import json
import sys
import warnings

from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, NoReturn, Protocol

from .config import FileEntry, ProjectConfig, ScrubbingOptions
from .exceptions import ScrubberError
from .processor import process_notebook, write_notes_file


def printe(*args, **kwargs) -> None:
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
        parser.add_argument(
            '--clear-tag',
            default='scrub-clear',
            help='Tag marking cells to clear',
        )
        parser.add_argument(
            '--clear-text',
            default='# TODO: Implement this',
            help='Text for cleared cells where unspecified',
        )
        parser.add_argument(
            '--omit-tag',
            default='scrub-omit',
            help='Tag marking cells to omit entirely',
        )
        parser.add_argument(
            '--note-tag',
            default='scrub-note',
            help='Tag marking cells to save to notes',
        )
        parser.add_argument(
            '--notes-file',
            type=Path,
            default=None,
            help='Path to write notes file (for cells with note tag)',
        )

    def __call__(self, args: argparse.Namespace) -> int:
        try:
            try:
                notebook = json.load(sys.stdin)
            except json.JSONDecodeError as e:
                raise ScrubberError(f'Invalid JSON input: {e}') from e
            except Exception as e:
                raise ScrubberError(f'Error reading input: {e}') from e

            options = ScrubbingOptions(
                clear_tag=args.clear_tag,
                clear_text=args.clear_text,
                omit_tag=args.omit_tag,
                note_tag=args.note_tag,
            )

            processed_notebook, notes_dict = process_notebook(notebook, options)

            # Handle notes
            if notes_dict:
                if args.notes_file is None:
                    # Warning mode: issue warning
                    warnings.warn(
                        f'Found {len(notes_dict)} cell(s) marked with note tag '
                        f'"{args.note_tag}", but no --notes-file specified. '
                        'Notes will not be saved.',
                        UserWarning,
                        stacklevel=2,
                    )
                else:
                    # Write notes file
                    write_notes_file(notes_dict, args.notes_file)

            try:
                json.dump(processed_notebook, sys.stdout, indent=1)
            except Exception as e:
                raise ScrubberError(f'Error writing output: {e}') from e

        except ScrubberError as e:
            printe(f'Error: {e}')
            sys.exit(1)
        except Exception as e:
            printe(f'Unexpected error: {e}')
            raise
        return 0


class ScrubProject:
    help: ClassVar[str] = (
        'Executes notebook scrubbing using project configuration. '
        'Searches for .ipynb-scrubber.toml or pyproject.toml with '
        '[tool.ipynb-scrubber] section.'
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

    def _process_file(
        self,
        file_entry: FileEntry,
        global_options: ScrubbingOptions,
    ) -> None:
        options = file_entry.get_options(global_options)

        if not file_entry.input.exists():
            raise ScrubberError(f'Input file not found: {file_entry.input}')

        try:
            with file_entry.input.open() as f:
                notebook = json.load(f)
        except json.JSONDecodeError as e:
            raise ScrubberError(f'Invalid JSON in {file_entry.input}: {e}') from e
        except OSError as e:
            raise ScrubberError(f'Error reading {file_entry.input}: {e}') from e

        processed_notebook, notes_dict = process_notebook(notebook, options)

        if notes_dict:
            if file_entry.notes_file is None:
                raise ScrubberError(
                    f'Found {len(notes_dict)} cell(s) with note tag '
                    f'"{options.note_tag}", but no notes-file specified in config',
                )
            write_notes_file(notes_dict, file_entry.notes_file)

        try:
            file_entry.output.parent.mkdir(parents=True, exist_ok=True)
            with file_entry.output.open('w') as f:
                json.dump(processed_notebook, f, indent=1)
        except OSError as e:
            raise ScrubberError(f'Error writing {file_entry.output}: {e}') from e

    def __call__(self, args: argparse.Namespace) -> int:
        try:
            if args.config_file is None:
                config = ProjectConfig.discover()
            else:
                config = ProjectConfig.from_file(args.config_file)
        except ScrubberError as e:
            printe(f'Error: {e}')
            return 1

        for file_entry in config.files:
            try:
                self._process_file(file_entry, config.global_options)
            except ScrubberError as e:
                printe(f'✗ Error processing {file_entry.input}: {e}')
                return 1
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
