# Contributing

Any contribution is welcome! This document provides guidelines for contributing to the obsidian-pdf-exporter project.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Architecture](#architecture)
- [Adding support for an Obsidian plugin](#adding-support-for-an-obsidian-plugin)
- [Adding a PDF template](#adding-a-pdf-template)
- [Testing](#testing)
- [Code Quality](#code-quality)
- [Documentation](#documentation)
- [Release Process](#release-process)
- [Pull Request Guidelines](#pull-request-guidelines)

## Getting Started

### Prerequisites

- Python 3.10 or higher
- Git
- `uv` (Python package manager)
- `jq` (for JSON processing)

### Install jq

```bash
sudo apt-get install jq
```

### Install `uv`

Following the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Add shell completion (optional):

```bash
echo 'eval "$(uv generate-shell-completion bash)"' >> ~/.bashrc
```

### Project Setup

1. **Fork and Clone the Repository**

   ```bash
   git clone https://github.com/Spenhouet/obsidian-pdf-exporter.git
   cd obsidian-pdf-exporter
   ```

2. **Install Dependencies**

   ```bash
   uv sync --all-groups
   ```

   This will:
   - Create a virtual environment
   - Install all dependencies (including development dependencies via dependency groups)
   - Install the project in editable mode

3. **Verify Installation**

   ```bash
   uv run obsidian-pdf-exporter --help
   uv run ope --help
   ```

## Development Workflow

### Running the Application

```bash
# Run with uv (recommended)
uv run obsidian-pdf-exporter [commands]
uv run ope [commands]

# Or activate the virtual environment
source .venv/bin/activate
obsidian-pdf-exporter [commands]
```

### Adding Dependencies

```bash
# Add runtime dependency
uv add package-name

# Add development dependency (to dev group)
uv add --group dev package-name

# Add to custom dependency group
uv add --group group-name package-name
```

### Updating Dependencies

```bash
# Update all dependencies
uv sync --upgrade

# Update specific dependency
uv sync --upgrade-package package-name
```

## Architecture

An export reads a folder of notes and turns it into one PDF. The work is
split into three layers. Each layer has one place where its parts are
listed.

1. Markdown dialect ([`core/dialect.py`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/core/dialect.py)).
   The pandoc reader extensions and pandoc arguments. The base is pandoc's
   `markdown` reader with `raw_html` and `lists_without_preceding_blankline`
   on and `raw_tex` off. Steps add what they need, for example `mark` for
   highlights, `hard_line_breaks` for line breaks or `--mathml` for math.
2. Obsidian core syntax ([`core/steps/`](https://github.com/Spenhouet/obsidian-pdf-exporter/tree/main/obsidian_pdf_exporter/core/steps/)).
   Every piece of syntax that Obsidian itself supports is a small step:
   frontmatter, comments, Bases, PDF embeds, embeds, block IDs, callouts, heading links,
   Markdown images, wiki links, image captions, headings, warnings about plugin code blocks,
   highlights, line breaks, tasks, math, footnotes, Mermaid, landscape
   diagrams, SVG images and table fixes. All steps are listed in
   `CORE_STEPS` in [`core/steps/__init__.py`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/core/steps/__init__.py).
3. Community plugins ([`plugins/`](https://github.com/Spenhouet/obsidian-pdf-exporter/tree/main/obsidian_pdf_exporter/plugins/)).
   Support for syntax from community Obsidian plugins and other tools:
   Folder Notes, Dataview, Excalidraw, Meta Bind, Block Link Plus, draw.io
   and pandoc citations. Plugins
   are found through an entry point, listed by `list-plugins` and can be
   turned off with `--disable-plugin`. They run inside the `plugins` step
   of layer 2.

```text
obsidian_pdf_exporter/
├── core/
│   ├── exporter.py         # export and redline: tree → markdown → HTML → PDF
│   ├── redline.py          # redline: the block and word diff of two assembled documents
│   ├── redline_html.py     # redline: summary, TOC marks, moves, change groups, styles
│   ├── redline_side_by_side.py, redline_collapse.py  # the side-by-side style, collapse
│   ├── blame.py            # --blame: match blocks to git blame, the strip next to the page
│   ├── htmltree.py         # parse and write the HTML as a tree (lxml)
│   ├── assets/             # CSS of the redline marks, side by side and the blame strip
│   ├── assemble.py         # runs the markdown hooks on every page
│   ├── pipeline.py         # the loops over the steps, one per stage
│   ├── dialect.py          # layer 1: pandoc reader extensions and arguments
│   ├── pandoc.py           # runs pandoc with a dialect
│   ├── steps/              # layer 2: one module per piece of core syntax
│   │   ├── __init__.py     # CORE_STEPS, the ordered list of steps
│   │   ├── base.py         # Step, PageContext, DocumentContext
│   │   ├── frontmatter.py, plugins.py, comments.py, bases.py, embeds.py, block_ids.py,
│   │   ├── callouts.py, heading_links.py, wiki_links.py, image_captions.py,
│   │   ├── headings.py, code_blocks.py, highlights.py, line_breaks.py, tasks.py, math.py,
│   │   ├── footnotes.py, landscape.py, pdf_embeds.py,
│   │   └── mermaid.py, svg_images.py, tables.py, base_css.py
│   ├── bases/              # Bases: expression parser, evaluator and views
│   ├── code.py             # outside_code: keeps fenced and inline code as written
│   └── embeds.py, callouts.py, wiki_links.py, mermaid.py, ...  # the work behind the steps
├── plugins/                # layer 3
│   ├── base.py             # ObsidianPlugin, PluginContext, DocumentContext
│   ├── registry.py         # entry-point + runtime discovery
│   ├── folder_notes/, dataview/, meta_bind/
│   ├── excalidraw/         # Excalidraw drawings drawn as SVG
│   ├── block_link_plus/    # ![[Note#^id-id]] ranges
│   ├── drawio/             # draw.io SVG labels
│   └── citations/          # [@key] citations with pandoc citeproc
└── templates/              # PDF templates (CSS, header, footer)
```

### Stages

A step overrides the hooks it needs:

| Hook                       | Runs on                                  | Order            |
|----------------------------|------------------------------------------|------------------|
| `process_markdown`         | each page, and embedded notes if `embedded = True` | `priority`       |
| `process_document`         | the assembled markdown of the whole document | `priority`   |
| `reader_extensions`, `pandoc_args` | builds the dialect for pandoc    | `priority`       |
| `process_html`             | the HTML that pandoc wrote               | `html_priority` (defaults to `priority`) |

An export runs them in this order: the markdown hooks on every page, the
document hooks, the template's `process_markdown`, pandoc, the HTML hooks,
the template's `process_html`, and WeasyPrint. With `--debug`, the build
folder keeps `assembled.md` (what pandoc reads) and `final.html` (what
WeasyPrint reads).

The order of the markdown steps matters. For example, `embeds` runs after
`html_comments`, so an embed inside an HTML comment is not expanded. It
runs before `block_ids`, so the block IDs in embedded text are removed
too. `bracket_links` runs after `wiki_links`, so real wiki links are
already resolved. The table in the docstring of
[`core/steps/__init__.py`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/core/steps/__init__.py)
gives the reason for each position.

Embedded notes (`![[Note]]`) run through the steps marked `embedded`
(`plugins`, `html_comments`, `bases`, `pdf_embeds`, `embeds`, `footnotes` and `wiki_links`) with the context of
the embedded note, so links and images resolve from its folder. The
embedded text then becomes part of the page and passes the remaining steps.

### Adding a core syntax step

Add a step only for syntax that Obsidian supports without a community
plugin. Everything else is a plugin (see below).

1. Put the step in a new module under `core/steps/`. Keep it thin and
   put larger parsing code in a module of its own under `core/`:

   ```python
   from obsidian_pdf_exporter.core.steps.base import PageContext
   from obsidian_pdf_exporter.core.steps.base import Step


   class SubscriptStep(Step):
       name = "subscript"
       description = "Render ~sub~ as subscript"
       priority = 115  # after image_captions (110), before title_heading (120)

       def reader_extensions(self, context):
           return ("subscript",)

       def process_markdown(self, content: str, context: PageContext) -> str:
           return content
   ```

2. Add the class to `CORE_STEPS` in `core/steps/__init__.py`, at the
   position of its priority, and to the table in the module docstring.
3. Leave code alone. Obsidian shows fenced code blocks and inline code
   as written, so wrap the rewrite in `outside_code` from
   [`core/code.py`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/core/code.py).
4. Never drop content silently. When the step sees syntax it can not
   render, it keeps it in a simple form and reports it with
   `context.warn(...)`, which prints a line starting with `Warning:`.
5. Add tests. [`test_steps.py`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/tests/unit/test_steps.py) checks the
   order of all steps, so update the expected lists there.
6. Describe the syntax in the docs (see [Documentation](#documentation)).

## Adding support for an Obsidian plugin

Obsidian plugins (Dataview, Meta Bind, Tasks, Templater, Excalidraw …)
introduce non-core syntax into markdown notes. To make those notes export
cleanly, the project carries one **plugin support module** per Obsidian
plugin. They all live under [`obsidian_pdf_exporter/plugins/`](https://github.com/Spenhouet/obsidian-pdf-exporter/tree/main/obsidian_pdf_exporter/plugins/),
one subpackage per plugin, so contributors have an obvious place to add a
new one.

### File layout

```text
obsidian_pdf_exporter/plugins/
├── base.py          # ObsidianPlugin base class + PluginContext, DocumentContext
├── registry.py      # entry-point + runtime discovery
├── dataview/
│   ├── __init__.py  # re-exports DataviewPlugin
│   ├── plugin.py    # the plugin class (thin)
│   ├── parse.py     # DQL grammar, on parsimmon.py
│   ├── index.py     # pages, fields, tasks of the vault
│   ├── engine.py    # query execution
│   ├── render.py    # Markdown output of the views
│   └── js/          # DataviewJS: dv API, Luxon, embedded V8
├── drawio/
│   ├── __init__.py
│   ├── plugin.py
│   └── svg.py       # draw.io label conversion
└── meta_bind/
    ├── __init__.py
    └── plugin.py
```

Keep the plugin class itself thin and put any non-trivial parsing,
indexing or rendering in sibling modules so it stays easy to test in
isolation. The Dataview package is the canonical example.

The currently bundled plugins are:

| Plugin         | What it covers                                           |
|----------------|----------------------------------------------------------|
| `folder_notes` | Map ``Folder/Folder.md`` onto its containing folder      |
| `dataview`     | Run Dataview queries, inline fields and DataviewJS       |
| `excalidraw`   | Turn embedded Excalidraw drawings into images            |
| `meta_bind`    | Resolve Meta Bind ``VIEW`` widgets, strip INPUT/BUTTON   |
| `block_link_plus` | Resolve ``![[Note#^id-id]]`` range embeds             |
| `drawio`       | Turn draw.io HTML labels in SVG images into SVG text     |
| `citations`    | Render ``[@key]`` citations with ``pandoc --citeproc``   |

### Walkthrough — adding a new plugin

Suppose you want to add support for the **Tasks** plugin so its
``- [ ] do thing 📅 2026-05-10`` syntax renders as a clean checkbox list.

#### 1. Create the package

```text
obsidian_pdf_exporter/plugins/tasks/
├── __init__.py
└── plugin.py
```

`__init__.py`:

```python
"""Support for the Obsidian `Tasks` plugin."""

from obsidian_pdf_exporter.plugins.tasks.plugin import TasksPlugin


__all__ = ["TasksPlugin"]
```

#### 2. Implement the plugin class

Every plugin subclasses
[`ObsidianPlugin`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/plugins/base.py) and overrides
``process_markdown(content, context)``. ``context`` is a
``PluginContext`` carrying the page's vault root, page folder,
frontmatter, and the user's ``--option key=value`` settings.

`plugin.py`:

```python
from __future__ import annotations

import re

from obsidian_pdf_exporter.plugins.base import ObsidianPlugin
from obsidian_pdf_exporter.plugins.base import PluginContext


_TASK_LINE = re.compile(r"^(\s*-\s\[)([ x/\-])(\]\s.+)$", re.MULTILINE)


class TasksPlugin(ObsidianPlugin):
    """Strip Tasks emoji-suffixes (📅, ⏫, …) and normalise checkbox state."""

    name = "tasks"
    description = "Render Tasks-plugin checkboxes without emoji metadata"
    priority = 50  # runs after dataview (10) and meta_bind (20)

    def process_markdown(self, content: str, context: PluginContext) -> str:
        # Drop the trailing emoji-tagged metadata that Tasks renders.
        content = re.sub(r"\s+[⏩-⏺✅❌\U0001F4C5][^\n]*", "", content)
        return _TASK_LINE.sub(lambda m: m.group(1) + m.group(2).lower() + m.group(3), content)
```

The pipeline guarantees:

- Frontmatter is already parsed and stripped before your plugin runs.
- Plugins run **before** embeds, callouts, wiki link resolution and image
  promotion, so anything your plugin produces flows through the rest of
  the pipeline like authored markdown would.
- Plugins also run on the content of embedded notes, with the context of
  the embedded note.
- ``context.vault_root`` may be ``None`` for ad-hoc exports outside a
  git repository — gracefully no-op in that case if you need vault-wide
  data (see the Dataview plugin for the pattern).

#### 3. Register it via an entry point

Add the new class to ``pyproject.toml``:

```toml
[project.entry-points."obsidian_pdf_exporter.obsidian_plugins"]
dataview = "obsidian_pdf_exporter.plugins.dataview:DataviewPlugin"
meta_bind = "obsidian_pdf_exporter.plugins.meta_bind:MetaBindPlugin"
tasks = "obsidian_pdf_exporter.plugins.tasks:TasksPlugin"
```

Re-install the project in editable mode so the entry point is picked up:

```bash
uv pip install -e .
```

Verify:

```bash
uv run obsidian-pdf-exporter list-plugins
```

#### 4. Add unit tests

Drop a file in `tests/unit/` that imports your plugin directly and feeds
it a few representative markdown snippets. Mirror the style in
[`test_plugins.py`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/tests/unit/test_plugins.py).

#### 5. Document it

Add a page under `docs/plugins/`, an example note under `examples/` and
its screenshot (see [Documentation](#documentation)), and list the plugin
in the table above.

### Plugin priority

`priority` is an integer — lower runs earlier. The built-ins use:

| Plugin         | Priority |
|----------------|----------|
| `folder_notes` | 5        |
| `dataview`     | 10       |
| `excalidraw`   | 15       |
| `meta_bind`    | 20       |
| `block_link_plus` | 30    |
| `drawio`       | 40       |
| `citations`    | 50       |

Pick a value that respects your dependencies (e.g. if your plugin
substitutes frontmatter fields like Meta Bind, run after Dataview so any
tables it generated are visible).

### Hooks

A plugin can override any of these methods on
[`ObsidianPlugin`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/plugins/base.py). All have
no-op defaults so you only implement what you need. A plugin that only
implements `process_markdown` keeps working:

| Hook                 | Stage                                | Used by                        |
|----------------------|--------------------------------------|--------------------------------|
| `find_folder_note`   | Tree building                        | `folder_notes`                 |
| `process_markdown`   | Per-page markdown rewrite            | `dataview`, `meta_bind`, `excalidraw` |
| `extract_block`      | Resolving `![[Note#^id]]` embeds     | `block_link_plus`              |
| `process_document`   | Assembled markdown of the whole document | `citations`                |
| `reader_extensions`, `pandoc_args` | Building the pandoc call (after `process_document`) | `citations` |
| `process_svg`        | Inlining SVG images into the HTML    | `drawio`                       |
| `process_html`       | HTML of the whole document           | none yet                       |

`find_folder_note(folder)` returns the markdown file that represents a
folder (or ``None``). Plugins are consulted in priority order; the
first non-None result wins. Use this when the Obsidian plugin you are
mirroring affects which file is the "page" for a folder. Examples:

- The bundled `folder_notes` plugin returns ``Folder/Folder.md``.
- A `readme_folder_notes` plugin could return ``Folder/README.md``.
- A frontmatter-driven plugin could return whichever file in the
  folder has ``folder-note: true``.

`process_markdown(content, context)` runs after frontmatter has been
stripped and before callouts / wiki links / image promotion. The
``context`` dataclass exposes ``vault_root``, ``page_folder``,
``frontmatter`` and the user's ``--option key=value`` settings.

`extract_block(body, block_id)` returns the text that `![[Note#^block_id]]`
selects in the note body, or ``None``. Plugins are asked in priority
order before core looks for a block marked ``^block_id``.

`process_document(markdown, context)` gets the assembled markdown of the
whole document, after the markdown hook ran on every page. The plugin can
then return pandoc reader extensions and arguments from
`reader_extensions(context)` and `pandoc_args(context)`, for example
`--citeproc` when it found citations.

`process_svg(svg, context)` rewrites each SVG image while it is inlined
into the HTML. `process_html(html, context)` gets the HTML of the whole
document after the core HTML steps and before the template. Both get a
``DocumentContext`` with the build folder, the options, the export
metadata and the template.

### Disabling and configuring plugins

Users can opt out of a single plugin per export with
``--disable-plugin <name>`` (repeatable). Free-form configuration is
forwarded through the existing ``--option key=value`` CLI flag and
exposed to every hook via ``context.options``.

### Third-party plugins

Plugins are not required to live in this repository. Anyone can publish
a separate Python distribution that registers a plugin under the same
``obsidian_pdf_exporter.obsidian_plugins`` entry point group; installing
it makes it instantly available to ``obsidian-pdf-exporter`` without
code changes here. Only add a plugin to this repository if it covers a
broadly used Obsidian plugin and is not better maintained as a separate
package.

## Adding a PDF template

PDF appearance (layout, header, footer, colour palette) is provided by
**templates**, a separate extension point that lives next to the plugin
system but is not the same thing. Templates plug into rendering, plugins
plug into markdown.

End users do **not** need to touch this repository to ship a custom
look. [Templates and styling](https://spenhouet.com/obsidian-pdf-exporter/templating/) in the docs covers the
no-Python options — drop-in CSS file, template directory with a
`template.yaml` manifest, or a named directory under
`~/.config/obsidian-pdf-exporter/templates/`. Reach for the steps below
only when your template needs to mutate markdown or HTML (i.e. requires
Python code).

Templates that ship inside this project live under
[`obsidian_pdf_exporter/templates/builtin/`](https://github.com/Spenhouet/obsidian-pdf-exporter/tree/main/obsidian_pdf_exporter/templates/builtin/);
each one ships a ``Template`` subclass plus its CSS file. To add one:

1. Drop a new package next to ``default`` and ``redline``.
2. Subclass
   [`Template`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/templates/base.py) and override
   ``get_css()`` (return CSS source) and optionally ``decorations(ctx)``
   to inject running header/footer HTML and ``@page`` rules.
3. Register the class under the ``obsidian_pdf_exporter.templates``
   entry point group in ``pyproject.toml`` and reinstall.

Branded or company-specific templates should usually be published as a
separate distribution rather than added here.

## Testing

We use `pytest` for testing. Tests are located in the `tests/` directory.

### Running Tests

```bash
# Run all tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_basic.py

# Run specific test
uv run pytest tests/test_basic.py::test_package_imports
```

### Writing Tests

1. **Create test files** in the `tests/` directory with the prefix `test_`
2. **Follow naming conventions**: `test_*.py` files, `test_*` functions
3. **Use descriptive test names** that explain what is being tested
4. **Add docstrings** to explain complex test scenarios

Example test structure:

```python
def test_feature_description() -> None:
    """Test that the feature works as expected."""
    # Arrange
    input_data = "test input"

    # Act
    result = function_under_test(input_data)

    # Assert
    assert result == expected_output
```

## Code Quality

### Linting with Ruff

We use `ruff` for Python linting and code formatting.

```bash
# Check code quality
uv run ruff check

# Auto-fix issues where possible
uv run ruff check --fix

# Check specific files or directories
uv run ruff check obsidian_pdf_exporter/
uv run ruff check tests/
```

### Code Style Guidelines

- **Line length**: Maximum 100 characters
- **Docstring style**: Google docstring convention
- **Import formatting**: One import per line (enforced by ruff)
- **Type hints**: Use type annotations for new code

### Pre-commit Workflow

Before committing:

1. **Run linting**: `uv run ruff check`
2. **Run tests**: `uv run pytest`
3. **Fix any issues** before committing

## Documentation

The documentation site is built with [Zensical](https://zensical.org/)
from `mkdocs.yml` and `docs/`, and published to GitHub Pages by
`.github/workflows/docs.yml` on every push to `main`.

```bash
uv sync --group docs
uv run zensical serve            # live preview on http://localhost:8000
uv run zensical build --strict   # what CI runs
```

Generated content:

- `docs/reference/cli.md` comes from the Typer app. Run
  `uv run python scripts/gen_cli_docs.py` after changing a command or
  flag. CI fails when the page is out of date.
- `docs/img/features/*.png` and `docs/img/templates/*.png` are rendered
  from the example vault in `examples/`. Each folder there (not starting
  with `_`) is one example and becomes `docs/img/features/<folder>.png`.
  Run `uv run python scripts/render_examples.py [name ...]` after a change
  that affects the output. It needs `pdftoppm` (poppler) and Node.js for
  Mermaid. Commit the images.
- `docs/img/redline/*.png` come from `examples/_redline/`. Each case
  folder there holds a `before/` and an `after/` version of a small vault.
  `uv run python scripts/render_redline_examples.py [case ...]` commits both
  into a temporary git repository (fixed dates, so the hashes do not
  change), runs `ope redline` in both styles and writes the images. The
  case `styles` renders `examples/_redline/_styles` in every combination
  of style, collapse and `--blame`, plus whole pages. Commit the images.
- `docs/llms.txt` and `docs/llms-full.txt` come from the pages. Run
  `uv run python scripts/gen_llms_txt.py` after adding or renaming a page.
  CI fails when they are out of date.

A feature page shows the example source next to its image with the
`ope-example` block, see any page under `docs/obsidian/`. The source is
included with `--8<-- "examples/<name>/<name>.md"`, so it cannot drift
from the note that was rendered.

## Release Process

> [!NOTE]
> Only relevant for maintainers.

### Automated Release

We use GitHub Actions for automated releases:

1. **Trigger Release Workflow**
   - Go to GitHub Actions tab
   - Run "Release" workflow
   - Choose version bump type (patch/minor/major) or specify custom version

2. **Automated Steps**
   - Updates version in `pyproject.toml`
   - Runs tests and builds
   - Creates Git tag
   - Publishes to PyPI
   - Creates GitHub release with auto-generated notes

## Pull Request Guidelines

### Before Submitting

1. **Create a feature branch**

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Run the full test suite**

   ```bash
   uv run ruff check
   uv run pytest
   uv build --no-sources  # Test build
   ```

3. **Update documentation** if needed

### PR Requirements

- All tests pass (verified by CI)
- Code passes linting (ruff check)
- Descriptive PR title and description
- Reference related issues if applicable
- Update tests for new functionality
- Update documentation for user-facing changes

## Development Environment

### Recommended Tools

- **IDE**: VS Code with Python extension
- **Git client**: Command line or your preferred GUI
- **Terminal**: Any modern terminal with shell completion

### VS Code Extensions

Recommended extensions for development:

- Python (Microsoft)
- Ruff (Astral Software)

### Project Structure

```text
obsidian-pdf-exporter/
├── .github/workflows/      # CI/CD workflows
├── obsidian_pdf_exporter/  # Main package, see Architecture
│   ├── __init__.py
│   ├── main.py            # CLI entry point
│   ├── core/              # Export pipeline, dialect and core syntax steps
│   ├── plugins/           # Obsidian community plugin support
│   └── templates/         # PDF templates
├── tests/                 # Test suite
├── pyproject.toml         # Project configuration
├── uv.lock                # Dependency lock file
└── CONTRIBUTING.md        # This file
```

## Getting Help

- **GitHub Issues**: For bug reports and feature requests
- **GitHub Discussions**: For questions and general discussion
- **Documentation**: https://spenhouet.com/obsidian-pdf-exporter/
