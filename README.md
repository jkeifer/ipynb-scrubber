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
  lines with a YAML block scalar
- **All cell types supported**: Works with code, markdown, and raw cells
- **Remove cells entirely**: Omit instructor-only cells from the output
- **Multiple syntax options**: Use cell tags or cell-type-appropriate comment syntax
- **Standard header syntax**: Code cell options are Quarto `#|` headers, parsed
  as the YAML they are
- **Preserve structure**: Maintain notebook structure and metadata, and carry
  through any fields this tool does not interpret
- **Clear all outputs**: Remove all cell outputs and execution counts for a
  clean slate
- **Project-wide processing**: Process multiple notebooks with a single command
  using a TOML config file
- **Never a partial result**: Outputs are moved into place only once written in
  full, and a failing notebook cancels the whole run rather than leaving a
  half-finished tree
- **Flexible CLI**: Unix-style stdin/stdout for single files, or config-based
  batch processing for projects
- **Python API**: Drive the same scrubbing from code (see
  [Python API](#python-api))

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
- `--notes-file PATH`: Path to write the notes file, required if any cell
  carries the note tag (see [Notes Files](#notes-files))

The three names must differ from one another. Pointing two of them at the same
string would make a marked cell ambiguous, so it is rejected:

```text
clear-tag, omit-tag and note-tag must all be distinct, but got
clear-tag='x', omit-tag='x', note-tag='scrub-note'
```

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

`clear-tag`, `omit-tag` and `note-tag` must differ from one another, both in
`[options]` and after a `[[files]]` entry's overrides are applied. An entry
that overrides one tag onto the value of another inherited from `[options]`
is rejected on that basis.

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

## Python API

Everything the commands do is available as a library. The public surface is
exported from the package root:

```python
from ipynb_scrubber import (
    FileEntry,
    Notebook,
    ProjectConfig,
    ScrubberError,
    ScrubbingOptions,
    process_notebook,
    scrub_file,
    scrub_files,
)
```

### Scrubbing a notebook in memory

`process_notebook` takes a parsed notebook and returns a new one alongside the
notes it collected. It leaves its argument alone and either returns a complete
exercise notebook or raises, so a failure part way through a notebook cannot
hand back something half-scrubbed:

```python
import json

from ipynb_scrubber import ScrubbingOptions, process_notebook

with open('lecture.ipynb') as f:
    notebook = json.load(f)

exercise, notes = process_notebook(notebook, ScrubbingOptions())
```

`notes` maps each note id to the original source of the cell it came from.
`ScrubbingOptions` carries the same four settings as the CLI flags, so
`ScrubbingOptions(clear_text='# YOUR CODE HERE')` mirrors
`--clear-text '# YOUR CODE HERE'`.

### Running a config

`ProjectConfig` loads the same TOML the `scrub-project` command reads, and
`scrub_files` runs a whole batch, reading each input and writing each exercise
notebook and notes file:

```python
from ipynb_scrubber import ProjectConfig, scrub_files

config = ProjectConfig.discover()      # or ProjectConfig.from_file(path)

scrub_files(config.files)
```

`scrub_files` is all-or-nothing across the batch: every output is staged first
and committed only once all of them have succeeded. Looping over `config.files`
and calling `scrub_file` on each is not equivalent — `scrub_file` is atomic for
its own entry, but a failure on the fourth notebook would leave the first three
committed.

Each `FileEntry` carries its own fully resolved `ScrubbingOptions`, with any
per-entry overrides already merged over the global ones, so `entry.options`
is what that notebook will actually be scrubbed with.

### Errors

Every failure caused by input or configuration raises `ScrubberError`, or one
of its two subclasses: `InvalidNotebookError` when a notebook is not shaped
like a notebook, and `ProcessingError` when a cell's option header cannot be
honored. Catching `ScrubberError` catches all of them. Anything else escaping
these functions is a defect in this tool rather than a problem with the input.

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
source — a `#| scrub-clear:` (or `<!-- scrub-clear: -->`) preceded by any other
line is not recognized as an option and is silently left as ordinary source.

The header is YAML, the same language Quarto's `#|` header is written in. Every
option is a `name: value` entry, the colon is required even when there is no
value, and values follow YAML's rules for quoting, typing and multi-line text.
Names the tool does not define, including Quarto's own options, are ignored.

The header is shared with whatever else writes in the same comments, so a
header that names no scrubber option is left alone: a `#|-----` divider or a
`#| fig-cap: A: B` that YAML cannot read yields no options rather than failing
the run. Once a scrubber option is named, the whole header must be readable
YAML, because an option the tool cannot see is an answer shipped to students.

#### Code Cells - Quarto Options

```python
#| scrub-clear:
def secret_solution():
    return 42

# Or with custom replacement text:
#| scrub-clear: "# WRITE YOUR SOLUTION HERE"
def another_solution():
    return "hidden"

# To save to notes and clear (requires an id):
#| scrub-note: exercise-1
def solution_with_notes():
    # This solution will be saved to the notes file
    # and then cleared from the student version
    return "answer"

# With custom replacement text:
#| scrub-note:
#|   id: exercise-2
#|   text: "# YOUR SOLUTION HERE"
def another_noted_solution():
    return "more answers"

# To omit entirely:
#| scrub-omit:
# This cell will be removed
print("Instructor only!")
```

#### Markdown Cells - HTML Comments

```markdown
<!-- scrub-clear: -->
## Answer

The solution is 42 because...

<!-- scrub-clear: "**Write your answer here**" -->
## Another Question

This answer will be replaced, with custom text.

<!-- scrub-omit: -->
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
- Empty text: `#| scrub-clear: ""` (results in empty cell)

An option written with no value at all — `#| scrub-clear:` — uses the default
`--clear-text` value.

**Replacement text containing `#` must be quoted or written as a block
scalar.** In YAML an unquoted `#` opens a comment that runs to the end of the
line, which would take the replacement text with it. Writing one is an error
naming the option, so text is never lost in silence. Both spellings keep the
`#`:

```python
#| scrub-clear: "# TODO: your code here"
```

```python
#| scrub-clear: |
#|   # TODO: your code here
```

Quoting is what other awkward text needs too: text starting with `*`, `&`,
`!`, `|`, `>`, `[`, `{`, `%`, `@` or `` ` ``, and text containing `: `.
Quoting is always safe, so quote when in doubt.

Values keep the type YAML gives them, and a value that is not text is an error
rather than a surprise. `#| scrub-clear: no` is the boolean false, so it fails
the run instead of clearing the cell to `False`; write `#| scrub-clear: "no"`
to mean the word.

#### Multi-line Replacement Text

Use a YAML block scalar for replacement text spanning several lines. The `|`
opens the block, content is indented relative to the option, and that
indentation is stripped:

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

A block scalar is verbatim: no comment stripping, no escapes, no quoting. That
makes it the right place for content full of backslashes or `#`, such as
regexes or LaTeX.

**Indent the content more deeply than the option line.** Content at the
option's own indentation is a sibling option instead of block content:

```python
#| scrub-clear: |
#| scrub-omit:          <- error, not a silent cell deletion
```

A cell's source header may carry at most one scrubber option, so that mistake
fails the run rather than quietly deleting the cell. Options that are not
scrubber options, such as Quarto's own, remain valid siblings:

```python
#| scrub-note: ex-1
#| echo: false
```

**Indent with spaces.** YAML forbids a tab in indentation, and a header
containing one is reported as such.

In a code cell, a blank line inside a block scalar may keep its `#|` marker or
drop it. Both of these yield `a`, a blank line, and `b`, because a blank line
belongs to the header whenever another `#|` line follows it:

```python
#| scrub-clear: |
#|   a
#|
#|   b
```

```python
#| scrub-clear: |
#|   a

#|   b
```

In a markdown cell the comment stays open across the block: the `|` is the last
thing on its line, the content follows, and a line containing only `-->` closes
the header. Blank lines up to it are kept verbatim, as in the example above. A
comment that is never closed is an error.

Repeating an option name within one cell's header is an error, as is reusing
the same `scrub-note` id anywhere in a notebook. Either would otherwise resolve
by keeping the last one, which in the note case discards an instructor
solution.

Combining scrubber options in one header is an error rather than a precedence
puzzle. Metadata tags are unaffected: a cell tagged both `scrub-omit` and
`scrub-note` is still simply omitted, and a `scrub-omit` tag still wins over a
`#| scrub-note:` in source.

#### Quoting and Escapes

A double-quoted value expands YAML's escapes, so `\n` and `\t` fit on a single
line:

```python
#| scrub-clear: "line one\nline two"
```

A single-quoted value is literal, which suits a regex:

```python
#| scrub-clear: 're.match(r"\d+", s)'
```

A block scalar is literal too, and handles several lines at once.

`--clear-text` and TOML `clear-text` use their own native mechanisms:

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

**Required format:** the option takes either the note id on its own, or a
mapping carrying the id and the text to leave in the cleared cell.

Just the id, which leaves the configured clear text behind:

```python
#| scrub-note: note-id
```

With custom replacement text:

```python
#| scrub-note:
#|   id: note-id
#|   text: "# YOUR CODE HERE"
```

With replacement text spanning several lines:

```python
#| scrub-note:
#|   id: note-id
#|   text: |
#|     multi-line replacement
#|     from the block below
```

`id` is required and must be a non-empty string. `text` is optional and
defaults to the configured clear text. Any other key is an error, as is a value
that is neither an id nor a mapping.

**The id is required.** A `scrub-note` with no id, an empty id, or a mapping
that omits `id`, is an error rather than a silent skip.

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

**A note cell requires somewhere to put the note.** If a notebook contains note
cells, `scrub-notebook` requires `--notes-file` and `scrub-project` requires
`notes-file` on that entry; without one the run fails and nothing is written.

Scrubbing a note cell replaces its body with a `# (See notes: <id>)` pointer, so
producing the exercise notebook without the notes file it points at would leave
that reference dangling.

**Note bodies are fenced in the notebook's own language,** read from
`metadata.language_info.name` or `metadata.kernelspec.language`. A notebook that
declares neither is fenced as `python`.

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
#| scrub-clear: "# TODO: Write your add function here"
def add(a, b):
    return a + b

result = add(1, 2)
print(f"Result: {result}")
```

**Markdown Cell 3** (HTML comment):

```markdown
<!-- scrub-clear: "**Write your explanation here**" -->
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
- **Unrecognized fields are carried through**: Notebook and cell keys this tool
  does not interpret are passed to the output untouched
- **A notebook is scrubbed whole or not at all**: An error anywhere in a
  notebook means no output for it, rather than a partially scrubbed result
- **Outputs are written atomically**: Each file is written beside its target and
  moved into place once complete, so no output is ever seen half-written. A
  `scrub-project` run stages every file first and commits only once all of them
  have succeeded, so a failing entry cancels the whole batch. Committing several
  files is several moves rather than one transaction, so an interruption during
  the commit itself can leave some entries written
- **Error handling**: A problem with a notebook, a config or a cell's options is
  reported as a short message with a non-zero exit status. Anything else is a
  defect in this tool and surfaces as a traceback

## License

Apache License 2.0

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request, but note
that comprehensive test coverage and clear justification for why the request
should be considered (keeping in mind new features increase the maintenance
burden) must be included.
