"""ipynb-scrubber: Generate exercise versions of Jupyter notebooks."""

from .processor import Notebook, process_notebook

__all__ = ['Notebook', 'process_notebook']
