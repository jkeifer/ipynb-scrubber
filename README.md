# ipynb-scrubber

Generate exercise versions of Jupyter notebooks by clearing solution cells and
removing instructor-only content.

> [!NOTE]
> This is a project made to satisfy a need on some personal projects. The
> behaivor has been tested to work for these projects but will not be supported
> for other uses.
>
> Issues will be reviewed if opened, and any legitimate bugs will be fixed, but
> new features or ideas will likely be rejected unless accompanied by a working
> pull request with comprehensive tests.
>
> Thanks for understanding.

## Features

- **Clear solution cells**: Replace cell contents with placeholder text while
  preserving structure
- **Remove cells entirely**: Omit instructor-only cells from the output
- **Preserve structure**: Maintain notebook structure and metadata
- **Clear all outputs**: Remove all cell outputs and execution counts for a
  clean slate
- **Support for tags**: Use cell tags or Quarto-style options to mark cells
- **Simple CLI**: Unix-style tool that reads from stdin and writes to stdout

## Installation

Install with a python package manager like `pip` or `uv`:

```bash
pip install ipynb-scrubber
```

## Usage

The tool takes a notebook on `stdin` and will write the scrubbed version to
`stdout`:

```bash
ipynb-scrubber < input.ipynb > output.ipynb
```

### Options

- `--clear-tag TAG`: Tag marking cells to clear (default: `scrub-clear`)
- `--clear-text TEXT`: Replacement text for cleared cells (default: `# TODO:
  Implement this`)
- `--omit-tag TAG`: Tag marking cells to omit entirely (default: `scrub-omit`)

### Examples

Using default settings:

```bash
ipynb-scrubber < lecture.ipynb > exercise.ipynb
```

Using custom tags:

```bash
ipynb-scrubber --clear-tag solution --omit-tag private < lecture.ipynb > exercise.ipynb
```

Using custom placeholder text:

```bash
ipynb-scrubber --clear-text "# YOUR CODE HERE" < lecture.ipynb > exercise.ipynb
```

## Marking Cells

There are two ways to mark cells for processing:

### 1. Cell Tags

Add tags to cells using Jupyter's tag interface:

- Add `scrub-clear` tag to solution cells that should be cleared
- Add `scrub-omit` tag to cells that should be removed entirely

### 2. Quarto Options

Use Quarto-style cell options at the beginning of code cells:

```python
#| scrub-clear
def secret_solution():
    return 42
```

```python
#| scrub-omit
# This cell will be removed entirely
print("Instructor only!")
```

## Example

### Input "notebook"

```python
# Cell 1 - Instructions (no tags)
# This will remain unchanged
print("Exercise: implement the function below")

# Cell 2 - Solution (tagged: scrub-clear)
def add(a, b):
    return a + b

result = add(1, 2)
print(f"Result: {result}")

# Cell 3 - Test (tagged: scrub-omit)
# This cell will be removed
assert add(1, 2) == 3
print("Tests pass!")
```

### Output "notebook"

```python
# Cell 1 - Instructions (unchanged)
# This will remain unchanged
print("Exercise: implement the function below")

# Cell 2 - Solution (cleared)
# TODO: Implement this

# (Cell 3 is omitted entirely)
```

## Behavior

- **All cell outputs are cleared**: Every cell has its output and execution
  count removed
- **Tagged cells are processed**:
  - Cells with the clear tag have their source code replaced with placeholder
    text
  - Cells with the omit tag are removed entirely from the output
- **Notebook metadata**: An `exercise_version` flag is added to the notebook
  metadata
- **Error handling**: Invalid notebooks produce helpful error messages

## License

Apache License 2.0

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
