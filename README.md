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
- **Save notes**: Collect code cell contents before clearing and save to a separate
  Markdown file for instructor reference with bidirectional linking
- **Custom replacement text**: Use cell-specific text instead of default placeholder
- **All cell types supported**: Works with code, markdown, and raw cells
- **Remove cells entirely**: Omit instructor-only cells from the output
- **Multiple syntax options**: Use cell tags or cell-type-appropriate comment syntax
- **Preserve structure**: Maintain notebook structure and metadata
- **Clear all outputs**: Remove all cell outputs and execution counts for a
  clean slate
- **Project-wide processing**: Process multiple notebooks with a single command
  using a TOML config file
- **Flexible CLI**: Unix-style stdin/stdout for single files, or config-based
  batch processing for projects

## Installation

Install with a python package manager like `pip` or `uv`:

```bash
pip install ipynb-scrubber
```

## Usage

The tool provides two commands for different workflows:

### Single Notebook: `scrub-notebook`

Process a single notebook via stdin/stdout (Unix-style):

```bash
ipynb-scrubber scrub-notebook < input.ipynb > output.ipynb
```

#### Options

- `--clear-tag TAG`: Tag marking cells to clear (default: `scrub-clear`)
- `--clear-text TEXT`: Replacement text for cleared cells where unspecified
  (default: `# TODO: Implement this`)
- `--omit-tag TAG`: Tag marking cells to omit entirely (default: `scrub-omit`)

#### Examples

Using default settings:

```bash
ipynb-scrubber scrub-notebook < lecture.ipynb > exercise.ipynb
```

Using custom tags:

```bash
ipynb-scrubber scrub-notebook \
    --clear-tag solution \
    --omit-tag private \
    < lecture.ipynb > exercise.ipynb
```

Using custom placeholder text:

```bash
ipynb-scrubber scrub-notebook \
    --clear-text "# YOUR CODE HERE" \
    < lecture.ipynb > exercise.ipynb
```

### Project-Wide: `scrub-project`

Process multiple notebooks using a configuration file:

```bash
ipynb-scrubber scrub-project
```

The command searches for configuration in the following order, starting from
the current directory and moving upward:

1. `.ipynb-scrubber.toml` (standalone config file)
1. `pyproject.toml` with `[tool.ipynb-scrubber]` section

This means you can run the command from any subdirectory of your project.

#### Configuration File Formats

**Option 1: Standalone `.ipynb-scrubber.toml`**

Create a `.ipynb-scrubber.toml` file with global options and file entries:

```toml
# Global options (optional - these are defaults)
[options]
clear-tag = "scrub-clear"
clear-text = "# TODO: Implement this"
omit-tag = "scrub-omit"

# File entries (required - at least one)
[[files]]
input = "lectures/lesson1.ipynb"
output = "exercises/lesson1.ipynb"

[[files]]
input = "lectures/lesson2.ipynb"
output = "exercises/lesson2.ipynb"
clear-text = "# YOUR CODE HERE"  # Override global option

[[files]]
input = "lectures/lesson3.ipynb"
output = "exercises/lesson3.ipynb"
clear-tag = "solution"  # Custom tag for this file
omit-tag = "instructor"
```

Each file entry supports:

- `input` (required): Path to source notebook
- `output` (required): Path where scrubbed notebook will be written
- `clear-tag` (optional): Override global clear tag
- `clear-text` (optional): Override global clear text
- `omit-tag` (optional): Override global omit tag

**Option 2: Using `pyproject.toml`**

Add configuration to your existing `pyproject.toml` under
`[tool.ipynb-scrubber]`:

```toml
# Global options (optional - these are defaults)
[tool.ipynb-scrubber.options]
clear-tag = "scrub-clear"
clear-text = "# TODO: Implement this"
omit-tag = "scrub-omit"

# File entries (required - at least one)
[[tool.ipynb-scrubber.files]]
input = "lectures/lesson1.ipynb"
output = "exercises/lesson1.ipynb"

[[tool.ipynb-scrubber.files]]
input = "lectures/lesson2.ipynb"
output = "exercises/lesson2.ipynb"
clear-text = "# YOUR CODE HERE"
```

This is convenient if you're already using `pyproject.toml` for your Python
project. The tool will automatically find and use this configuration.

#### Custom Config File

Specify a different config file location (bypasses automatic discovery):

```bash
ipynb-scrubber scrub-project --config-file path/to/config.toml
```

## Marking Cells

There are two ways to mark cells for processing:

### 1. Cell Tags (All Cell Types)

Add tags to cells using Jupyter's tag interface. This works for all cell types
(code, markdown, raw):

- Add `scrub-clear` tag to solution cells that should be cleared
- Add `scrub-omit` tag to cells that should be removed entirely

**Note:** The `scrub-note` tag requires source-based syntax (see below) and only
works for code cells.

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

# To save to notes and clear (requires ID):
#| scrub-note: exercise-1
def solution_with_notes():
    # This solution will be saved to the notes file
    # and then cleared from the student version
    return "answer"

# With custom replacement text:
#| scrub-note: exercise-2 | # YOUR SOLUTION HERE
def another_noted_solution():
    return "more answers"

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

**Note:** The `scrub-note` option is only available for code cells.

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

### Notes Files

**Code cells only** - Cells marked with the `scrub-note` tag will have their
content saved to a separate Markdown file before being cleared from the
student version. This creates bidirectional linking between the exercise and
solutions.

**Required format:**
```python
#| scrub-note: note-id
#| scrub-note: note-id | custom replacement text
```

The `note-id` is required and should be a human-readable identifier (e.g.,
`exercise-1`, `question-2a`). When the cell is cleared, a reference comment
is automatically added:

```python
# TODO: Implement this
# (See notes: exercise-1)
```

This creates a clear link from the exercise notebook to the notes file.

**Behavior by command:**

- **`scrub-notebook`**: If note cells are found but no `--notes-file` is
  specified, a warning is issued but processing continues
- **`scrub-project`**: If note cells are found but no `notes-file` is specified
  in the config, processing fails with an error

**Notes file format:**

The notes file is generated in Markdown format with human-readable IDs:

```markdown
# Notebook Notes

This file contains the original content of cells marked for note-taking.

## exercise-1

\```python
def secret_solution():
    return 42
\```

## question-2a

\```python
def another_solution():
    return "answer"
\```

---
*Generated by ipynb-scrubber*
```

**Usage examples:**

```bash
# scrub-notebook with notes
ipynb-scrubber scrub-notebook --notes-file solutions.md < lecture.ipynb > exercise.ipynb

# scrub-project with notes in config
# .ipynb-scrubber.toml:
# [[files]]
# input = "lecture.ipynb"
# output = "exercise.ipynb"
# notes-file = "solutions.md"
```

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
burden) must be included.
