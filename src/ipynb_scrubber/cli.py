import argparse
import io
import os
import sys

from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar, NoReturn, Protocol

from .actions import OPTIONS, ScrubbingOptions
from .config import ProjectConfig
from .exceptions import MissingNotesDestinationError, ScrubberError, reporting
from .notes import require_destination
from .processor import scrub
from .project import scrub_files
from .staging import commit_all, stage, staged_batch

_DEFAULTS = ScrubbingOptions()


def printe(*args: object, **kwargs: Any) -> None:
    print(*args, file=sys.stderr, **kwargs)  # noqa: T201


def _discard_unwritable_stdout() -> None:
    """Throw away stdout's buffer by pointing its descriptor at the null device.

    A failed write leaves the notebook sitting in stdout's ``BufferedWriter``,
    and at shutdown CPython flushes ``sys.stdout`` regardless. That flush hits
    the same descriptor that just failed, so the user gets an
    ``Exception ignored while flushing sys.stdout`` traceback after the error we
    already reported, and CPython replaces our exit status with 120. Redirecting
    the descriptor is CPython's own remedy for this (see the note on SIGPIPE in
    the :mod:`signal` docs): the buffered bytes go to the null device instead of
    failing again, which is what we want anyway, since a notebook that could not
    be delivered is not worth retrying a piece of.

    Call this only where a write to stdout has failed, and only once the
    contents of the buffer are known to be unwanted.
    """
    try:
        fileno = sys.stdout.fileno()
    except io.UnsupportedOperation:
        # Nothing to redirect: stdout has been replaced by something buffering
        # in memory rather than into a descriptor -- pytest's capture, say -- so
        # the shutdown flush has no failing descriptor to reach.
        return

    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, fileno)
    finally:
        os.close(devnull)


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
        'by the user. A notes file, if one is asked for, '
        'is written only once the exercise notebook has '
        'reached stdout, so it never describes a notebook '
        'that was never delivered.'
    )
    name = 'scrub-notebook'

    def set_args(self, parser: argparse.ArgumentParser) -> None:
        for option in OPTIONS:
            parser.add_argument(
                f'--{option.key}',
                dest=option.field,
                default=getattr(_DEFAULTS, option.field),
                help=option.help,
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
            options = ScrubbingOptions(
                **{option.field: getattr(args, option.field) for option in OPTIONS},
            )

            with reporting('Error reading input'):
                # Read the raw bytes: a notebook's encoding is a property of
                # the notebook, not of the locale the tool happens to run in.
                data = sys.stdin.buffer.read()

            result = scrub(data, options)

            notes_file = args.notes_file
            try:
                require_destination(result.note_count, notes_file, options.note_tag)
            except MissingNotesDestinationError as e:
                raise ScrubberError(f'{e} Pass --notes-file PATH.') from e

            with staged_batch() as staged:
                if result.notes_text is not None:
                    with reporting('Error writing notes file'):
                        staged.append(stage(notes_file, result.notes_text))

                # Left explicit rather than given to ``reporting``: a failed
                # write has to be discarded before anything else can raise.
                try:
                    # Bytes again, for the same reason as stdin: the output
                    # encoding belongs to the notebook, not to the terminal it
                    # is piped into.
                    sys.stdout.buffer.write(result.notebook_text.encode('utf-8'))
                    sys.stdout.buffer.flush()
                except OSError as e:
                    _discard_unwritable_stdout()
                    raise ScrubberError(f'Error writing output: {e}') from e

                # Committed only now: notes are worth having only alongside the
                # notebook they annotate, so a consumer that went away mid-write
                # must not be left a notes file describing what it never got.
                with reporting(
                    'Error writing notes file after the notebook reached stdout',
                ):
                    commit_all(staged)

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
