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
- **Multi-line replacement content**: Write replacement text spanning several
  lines with a `|` block, or with escape sequences on a single line
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
- `--note-tag TAG`: Option name marking cells to save to notes
  (default: `scrub-note`)
- `--notes-file PATH`: Path to write the notes file for cells with the note
  tag (see [Notes Files](#notes-files))

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

A `pyproject.toml` encountered during the search that cannot be read or
parsed as TOML stops the search with an error, rather than being skipped.
Since the file cannot be parsed, there is no way to know whether it would
have contained a `[tool.ipynb-scrubber]` section, so neither "keep
searching" nor "no config found" would be a trustworthy result. A readable
`pyproject.toml` with no `[tool.ipynb-scrubber]` section is unaffected and
is skipped as before.

#### Configuration File Formats

**Option 1: Standalone `.ipynb-scrubber.toml`**

Create a `.ipynb-scrubber.toml` file with global options and file entries:

```toml
# Global options (optional - these are defaults)
[options]
clear-tag = "scrub-clear"
clear-text = "# TODO: Implement this"
omit-tag = "scrub-omit"
note-tag = "scrub-note"

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
- `note-tag` (optional): Override global note tag
- `notes-file` (optional): Path to write the notes file for this notebook

Overrides are presence-based, not truthiness-based: a file entry that sets
`clear-text = ""` gets an empty string for that file rather than falling back
to the global default.

Unknown keys anywhere in the config — the top level, `[options]`, or a
`[[files]]` entry — are rejected, and the error names the invalid key and
lists the valid ones, so a misspelled `clear-tagg` fails the run instead of
silently leaving solution cells unscrubbed.

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

**Note:** The `scrub-note` option requires source-based syntax (see below) and
is valid only in code cells; using it elsewhere is an error.

### 2. Source-Based Options (Code & Markdown)

Use cell-type-appropriate syntax for more control, including custom replacement
text. The option header must be the first non-blank content in the cell's
source — a `#| scrub-clear` (or `<!-- scrub-clear -->`) preceded by any other
line is not recognized as an option and is silently left as ordinary source:

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

**Note:** The `scrub-note` option is valid only in code cells. Using it in a
markdown cell is an error and fails the run — it is never silently ignored, so
a note tag on a markdown answer cell can't accidentally ship the answer to
students.

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

#### Multi-line Replacement Text

Use a `|` block for replacement text spanning several lines. Content is
indented relative to the option, and that indentation is stripped:

```python
#| scrub-clear: |
#|   def add(a, b):
#|       # TODO: your code here
#|       pass
def add(a, b):
    return a + b
```

```markdown
<!-- scrub-clear: |
  **Write your answer here**

  Show your work.
-->
## Solution
```

**Indent the content more deeply than the option line.** Content at or below
the option's own indentation ends the block and is then read as further
options:

```python
#| scrub-clear: |
#| def add(a, b):
#|     pass
```

That yields an empty replacement plus two meaningless options. Where it would
be dangerous — an under-indented line naming another scrubber option — it is
an error instead, because a cell may carry at most one scrubber option in its
source header:

```python
#| scrub-clear: |
#| scrub-omit          <- error, not a silent cell deletion
```

Options that are not scrubber options, such as Quarto's own, remain valid
siblings:

```python
#| scrub-note: ex-1 |
#| echo: false
```

Tabs are accepted and expanded to their normal width when measuring
indentation, so a tab-indented block works.

In a code block, an interior blank line must still carry its `#|` marker. A
genuinely empty line ends the block entirely, so the first of these yields
only `a` while the second yields `a`, a blank line, and `b`:

```python
#| scrub-clear: |
#|   a

#|   b
```

```python
#| scrub-clear: |
#|   a
#|
#|   b
```

Note that in the first form the `#|   b` line, once the block has ended, is
read as a *new option* named `b`. It is ignored because no such scrubber
option exists, but keep the `#|` marker on interior blank lines to avoid the
surprise.

The markdown form differs here: it ends at a line containing only `-->`, and
until then a real blank line is kept verbatim, as in the example above.

A markdown block also requires the comment to stay *open*. The `|` must be the
last thing on the line, with the `-->` on its own line later. A closed
one-liner like `<!-- scrub-clear: | -->` is read as ordinary inline text, and
the replacement becomes the literal string `|`.

Blocks are taken verbatim — no escape processing — which makes them the right
place for content containing backslashes, such as regexes or LaTeX.

Inline text and a block are mutually exclusive: writing text on the option line
*and* opening a block is an error, not a concatenation.

```python
#| scrub-clear: some text |
#|   more text
```

Use one or the other. If the trailing `|` was meant as literal text rather than
a block opener, escape it as `\|`.

Repeating an option name within one cell's header is an error, as is reusing
the same `scrub-note` id anywhere in a notebook — both previously resolved
silently by keeping the last one, which in the note case discarded an
instructor solution.

A cell's source header may carry at most one scrubber option. Combining them
in the header is an error rather than a precedence puzzle. Metadata tags are
unaffected: a cell tagged both `scrub-omit` and `scrub-note` is still simply
omitted, and a `scrub-omit` tag still wins over a `#| scrub-note:` in source.

#### Escape Sequences

Single-line values expand `\n`, `\t`, `\\`, and `\|`. Any other backslash
sequence is left untouched, so `#| scrub-clear: re.match(r"\d+")` works as
written.

Escapes apply only to in-cell options, because that is the only place with no
other way to write a newline. `--clear-text` and TOML `clear-text` use their
own native mechanisms instead:

```bash
ipynb-scrubber scrub-notebook \
    --clear-text $'def add(a, b):\n    # TODO\n    pass' \
    < lecture.ipynb > exercise.ipynb
```

```toml
clear-text = """
def add(a, b):
    # TODO
    pass"""
```

A `\n` in a TOML *literal* string (single quotes) stays literal.

### Notes Files

**Code cells only** - A code cell carrying a `#| scrub-note: <id>` option has
its content saved to a separate Markdown file before being cleared from the
student version. This creates bidirectional linking between the exercise and
solutions.

Markdown notes are not supported. The reference text inserted into the cleared
cell is `# (See notes: <id>)`, which renders as a heading rather than a
comment in a markdown cell, so supporting them requires a per-cell-type
reference format.

**There is no `scrub-note` cell tag.** Unlike `scrub-clear` and `scrub-omit`,
the option is source-only: a note needs an id, and a Jupyter metadata tag has
nowhere to put one. A cell tagged `scrub-note` fails the run rather than being
ignored, because ignoring it would ship the solution to students. (A cell
tagged both `scrub-omit` and `scrub-note` is simply omitted.)

**Required format:**
```python
#| scrub-note: note-id
#| scrub-note: note-id | custom replacement text
#| scrub-note: note-id |
#|   multi-line replacement
#|   from the block below
```

The id is split from the replacement text at the first `|`. A block always
supplies the replacement, never the id. **The id is required** — a `scrub-note`
without one is an error.

Whitespace around the splitting `|` is irrelevant, so these all parse to the id
`ex-1` with the replacement `text`:

```python
#| scrub-note: ex-1 | text
#| scrub-note: ex-1|text
#| scrub-note: ex-1 |text
```

These, by contrast, are all errors rather than silent skips:

```python
#| scrub-note
#| scrub-note:
#| scrub-note: | text
```

As with `scrub-clear`, inline replacement text and a block are mutually
exclusive — `#| scrub-note: ex-1 | some text |` followed by block lines is an
error. Use one or the other, or escape a genuinely intended trailing pipe as
`\|`.

The `note-id` should be a human-readable identifier (e.g., `exercise-1`,
`question-2a`). When the cell is cleared, a reference comment is automatically
added:

```python
# (See notes: exercise-1)
# TODO: Implement this
```

This creates a clear link from the exercise notebook to the notes file.

**Note ids must be unique within a notebook.** Reusing one is an error that
names both cells involved, for example:

```text
Cell 2: Duplicate note id 'ex-1'; already used by cell 0. Note ids must be
unique within a notebook
```

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
