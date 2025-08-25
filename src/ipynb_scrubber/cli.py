import argparse
import json
import sys

from .exceptions import ScrubberError
from .processor import process_notebook


def cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            'Reads a Jupyter notebook from stdin, '
            'processes it to clear cell outputs, '
            'and writes the exercise version to stdout. '
            'Cells tagged with the omit tag are omitted '
            'from the exercise version, while those tagged '
            'with the clear tag are cleared and a message '
            'is added to indicate they are to be completed '
            'by the user.'
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--clear-tag',
        default='scrub-clear',
        help='Tag marking cells to clear',
    )
    parser.add_argument(
        '--clear-text',
        default='# TODO: Implement this',
        help='Text for cleared cells',
    )
    parser.add_argument(
        '--omit-tag',
        default='scrub-omit',
        help='Tag marking cells to omit entirely',
    )
    args = parser.parse_args()

    try:
        try:
            notebook = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            raise ScrubberError(f'Invalid JSON input: {e}') from e
        except Exception as e:
            raise ScrubberError(f'Error reading input: {e}') from e

        processed_notebook = process_notebook(
            notebook,
            clear_tag=args.clear_tag,
            clear_text=args.clear_text,
            omit_tag=args.omit_tag,
        )

        try:
            json.dump(processed_notebook, sys.stdout, indent=2)
        except Exception as e:
            raise ScrubberError(f'Error writing output: {e}') from e

    except ScrubberError as e:
        print(f'Error: {e}', file=sys.stderr)  # noqa: T201
        sys.exit(1)
    except Exception as e:
        print(f'Unexpected error: {e}', file=sys.stderr)
        # ruff: noqa T202
        raise


if __name__ == '__main__':
    cli()
