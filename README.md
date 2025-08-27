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
- **Custom replacement text**: Use cell-specific text instead of default placeholder
- **All cell types supported**: Works with code, markdown, and raw cells
- **Remove cells entirely**: Omit instructor-only cells from the output
- **Multiple syntax options**: Use cell tags or cell-type-appropriate comment syntax
- **Preserve structure**: Maintain notebook structure and metadata
- **Clear all outputs**: Remove all cell outputs and execution counts for a
  clean slate
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
- `--clear-text TEXT`: Replacement text for cleared cells where unspecified
  (default: `# TODO: Implement this`)
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

### 1. Cell Tags (All Cell Types)

Add tags to cells using Jupyter's tag interface. This works for all cell types
(code, markdown, raw):

- Add `scrub-clear` tag to solution cells that should be cleared
- Add `scrub-omit` tag to cells that should be removed entirely

### 2. Source-Based Options (Code & Markdown)

Use cell-type-appropriate syntax for more control, including custom replacement
text:

#### Code Cells - Quarto Options

```python
#| scrub-clear
def secret_solution():
    return 42

# Or with custom replacement text:
#| scrub-clear: # WRITE YOUR SOLUTION HERE
def another_solution():
    return "hidden"

# To omit entirely:
#| scrub-omit
# This cell will be removed
print("Instructor only!")
```

#### Markdown Cells - HTML Comments

```markdown
<!-- scrub-clear -->
## Answer

The solution is 42 because...

<!-- Or with custom replacement text: -->
<!-- scrub-clear: **Write your answer here** -->
## Another Question

This answer will be replaced.

<!-- To omit entirely: -->
<!-- scrub-omit -->
## Instructor Notes

These notes are only for the instructor.
```

#### Raw Cells - Tags Only

Raw cells only support metadata tags to avoid format conflicts:

```python
# Cell metadata: {"tags": ["scrub-clear"]}
$$\int_0^1 x^2 dx = \frac{1}{3}$$

# Cell metadata: {"tags": ["scrub-omit"]}
% This LaTeX comment will be omitted entirely
```

### Custom Replacement Text

When using source-based options, you can specify custom text to replace the
cleared content:

- `#| scrub-clear: Your custom text` (code cells)
- `<!-- scrub-clear: Your custom text -->` (markdown cells)
- Empty text: `#| scrub-clear:` (results in empty cell)

If no custom text is provided, the default `--clear-text` value is used.

## Example

### Input Notebook

**Code Cell 1** (no tags):

```python
# Instructions - this will remain unchanged
print("Exercise: implement the functions below")
```

**Code Cell 2** (Quarto option with custom text):

```python
#| scrub-clear: # TODO: Write your add function here
def add(a, b):
    return a + b

result = add(1, 2)
print(f"Result: {result}")
```

**Markdown Cell 3** (HTML comment):

```markdown
<!-- scrub-clear: **Write your explanation here** -->
## Solution Explanation

The add function works by using the + operator...
```

**Code Cell 4** (cell tag - will be omitted):

```python
# Cell has metadata: {"tags": ["scrub-omit"]}
# This cell will be removed entirely
assert add(1, 2) == 3
print("Tests pass!")
```

### Output Notebook

**Code Cell 1** (unchanged):

```python
# Instructions - this will remain unchanged
print("Exercise: implement the functions below")
```

**Code Cell 2** (cleared with custom text):

```python
# TODO: Write your add function here
```

**Markdown Cell 3** (cleared with custom text):

```markdown
**Write your explanation here**
```

**Code Cell 4** (omitted entirely)

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

Contributions are welcome! Please feel free to submit a Pull Request, but note
that comprehensive test coverage and clear justification for why the request
should be considered (keeping in mind new features increase the maintenance
burden) should be included.
