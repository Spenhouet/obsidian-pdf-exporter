# Contributing

Any contribution is welcome! This document provides guidelines for contributing to the obsidian-pdf-exporter project.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Adding support for an Obsidian plugin](#adding-support-for-an-obsidian-plugin)
- [Adding a PDF template](#adding-a-pdf-template)
- [Testing](#testing)
- [Code Quality](#code-quality)
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

## Adding support for an Obsidian plugin

Obsidian plugins (Dataview, Meta Bind, Tasks, Templater, Excalidraw …)
introduce non-core syntax into markdown notes. To make those notes export
cleanly, the project carries one **plugin support module** per Obsidian
plugin. They all live under [`obsidian_pdf_exporter/plugins/`](obsidian_pdf_exporter/plugins/),
one subpackage per plugin, so contributors have an obvious place to add a
new one.

### File layout

```text
obsidian_pdf_exporter/plugins/
├── base.py          # ObsidianPlugin base class + PluginContext dataclass
├── registry.py      # entry-point + runtime discovery
├── dataview/
│   ├── __init__.py  # re-exports DataviewPlugin
│   ├── plugin.py    # the plugin class (thin)
│   └── engine.py    # DQL parser + renderer (heavy lifting)
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
| `dataview`     | Render Dataview DQL ``TABLE`` / ``LIST`` queries         |
| `meta_bind`    | Resolve Meta Bind ``VIEW`` widgets, strip INPUT/BUTTON   |

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
[`ObsidianPlugin`](obsidian_pdf_exporter/plugins/base.py) and overrides
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
    priority = 30  # runs after dataview (10) and meta_bind (20)

    def process_markdown(self, content: str, context: PluginContext) -> str:
        # Drop the trailing emoji-tagged metadata that Tasks renders.
        content = re.sub(r"\s+[⏩-⏺✅❌\U0001F4C5][^\n]*", "", content)
        return _TASK_LINE.sub(lambda m: m.group(1) + m.group(2).lower() + m.group(3), content)
```

The pipeline guarantees:

- Frontmatter is already parsed and stripped before your plugin runs.
- Plugins run **before** callouts, wiki link resolution and image
  promotion, so anything your plugin produces flows through the rest of
  the pipeline like authored markdown would.
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
[`test_plugins.py`](tests/unit/test_plugins.py).

#### 5. Document it

Mention the new plugin in the README's feature list and add a note in
this file under "supported plugins" if the support is partial.

### Plugin priority

`priority` is an integer — lower runs earlier. The built-ins use:

| Plugin         | Priority |
|----------------|----------|
| `folder_notes` | 5        |
| `dataview`     | 10       |
| `meta_bind`    | 20       |

Pick a value that respects your dependencies (e.g. if your plugin
substitutes frontmatter fields like Meta Bind, run after Dataview so any
tables it generated are visible).

### Hooks

A plugin can override either or both of these methods on
[`ObsidianPlugin`](obsidian_pdf_exporter/plugins/base.py); both have
no-op defaults so you only implement what you need:

| Hook                 | Stage                      | Used by                        |
|----------------------|----------------------------|--------------------------------|
| `find_folder_note`   | Tree building              | `folder_notes`                 |
| `process_markdown`   | Per-page markdown rewrite  | `dataview`, `meta_bind`        |

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

### Disabling and configuring plugins

Users can opt out of a single plugin per export with
``--disable-plugin <name>`` (repeatable). Free-form configuration is
forwarded through the existing ``--option key=value`` CLI flag and
exposed to your ``process_markdown`` via ``context.options``.

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
look. The README's [Templates](README.md#templates) section covers the
no-Python options — drop-in CSS file, template directory with a
`template.yaml` manifest, or a named directory under
`~/.config/obsidian-pdf-exporter/templates/`. Reach for the steps below
only when your template needs to mutate markdown or HTML (i.e. requires
Python code).

Templates that ship inside this project live under
[`obsidian_pdf_exporter/templates/builtin/`](obsidian_pdf_exporter/templates/builtin/);
each one ships a ``Template`` subclass plus its CSS file. To add one:

1. Drop a new package next to ``default`` and ``redline``.
2. Subclass
   [`Template`](obsidian_pdf_exporter/templates/base.py) and override
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
├── obsidian_pdf_exporter/  # Main package
│   ├── __init__.py
│   ├── main.py            # CLI entry point
│   └── utils/             # Utility modules
├── tests/                 # Test suite
├── pyproject.toml         # Project configuration
├── uv.lock                # Dependency lock file
└── CONTRIBUTING.md        # This file
```

## Getting Help

- **GitHub Issues**: For bug reports and feature requests
- **GitHub Discussions**: For questions and general discussion
- **Documentation**: Check the README and code comments
