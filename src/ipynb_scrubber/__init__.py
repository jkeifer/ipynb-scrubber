"""ipynb-scrubber: Generate exercise versions of Jupyter notebooks."""

from .__version__ import __version__
from .config import FileEntry, ProjectConfig
from .exceptions import InvalidNotebookError, ProcessingError, ScrubberError
from .notebook import Cell, Notebook
from .options import ScrubbingOptions
from .processor import (
    NotebookScrubResult,
    ScrubResult,
    process_notebook,
    scrub,
    scrub_parsed,
)
from .project import scrub_files

__all__ = [
    'Cell',
    'FileEntry',
    'InvalidNotebookError',
    'Notebook',
    'NotebookScrubResult',
    'ProcessingError',
    'ProjectConfig',
    'ScrubResult',
    'ScrubberError',
    'ScrubbingOptions',
    '__version__',
    'process_notebook',
    'scrub',
    'scrub_files',
    'scrub_parsed',
]
