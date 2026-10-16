---
title: Write a plugin
description: Add support for another Obsidian community plugin, in this repository or as a separate Python package.
---

# Write a plugin

A plugin support module is a subclass of [`ObsidianPlugin`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/plugins/base.py) that overrides the hooks it needs. It can live in this repository or in a package of its own. Support for core Obsidian syntax is a step, not a plugin, see [Contributing](../contributing.md).

## Example: strip Tasks metadata

The [Tasks](https://github.com/obsidian-tasks-group/obsidian-tasks) plugin adds emoji metadata such as `📅 2026-05-10` to task lines. This plugin removes it:

```python title="my_ope_plugins/tasks.py"
from __future__ import annotations

import re

from obsidian_pdf_exporter.plugins.base import ObsidianPlugin
from obsidian_pdf_exporter.plugins.base import PluginContext

_METADATA = re.compile(r"\s+[⏫🔼🔽📅⏳🛫✅❌🔁][^\n]*")


class TasksPlugin(ObsidianPlugin):
    """Remove the emoji metadata of the Tasks plugin."""

    name = "tasks"
    description = "Remove Tasks plugin metadata from task lines"
    priority = 60  # after the built-in plugins (5 to 50)

    def process_markdown(self, content: str, context: PluginContext) -> str:
        return _METADATA.sub("", content)
```

Register it under the entry point group in the package's `pyproject.toml`:

```toml
[project.entry-points."obsidian_pdf_exporter.obsidian_plugins"]
tasks = "my_ope_plugins.tasks:TasksPlugin"
```

Install it next to ope and check that it is found:

```bash
uv tool install obsidian-pdf-exporter --with ./my-ope-plugins
ope list-plugins
```

## Hooks

All hooks have no-op defaults.

| Hook | Runs | Used by |
| ---- | ---- | ------- |
| `find_folder_note(folder)` | While the page tree is built. Returns the note of a folder or `None`. The first plugin with a result wins. | `folder_notes` |
| `process_markdown(content, context)` | On each page and on embedded notes, after the frontmatter is parsed and before embeds, callouts and wiki links. | `dataview`, `meta_bind`, `excalidraw` |
| `process_document(markdown, context)` | On the assembled Markdown of the whole document, after `process_markdown` ran on every page. | `citations` |
| `reader_extensions(context)`, `pandoc_args(context)` | When the pandoc call is built, after `process_document`. Return extra reader extensions and arguments, such as `--citeproc`. | `citations` |
| `extract_block(body, block_id)` | For `![[Note#^id]]`. Returns the selected text or `None`, before core looks for `^id`. | `block_link_plus` |
| `process_svg(svg, context)` | On each SVG image while it is inlined. | `drawio` |
| `process_html(html, context)` | On the HTML of the whole document, after the core HTML steps and before the template. | `meta_bind` |

`PluginContext` (markdown hooks) has `vault_root`, `page_folder`, `frontmatter`, `options` and `vault_index`. `vault_root` is `None` when the export runs outside a vault, so a plugin that needs vault-wide data should do nothing then.

`DocumentContext` (SVG and HTML hooks) has `build_dir`, `options`, `root`, `export` (title, version, date), `template`, `plugins`, `redline` and `log`.

## Priority

`priority` is an integer, lower runs earlier. The built-ins use 5 (`folder_notes`), 10 (`dataview`), 15 (`excalidraw`), 20 (`meta_bind`), 30 (`block_link_plus`), 40 (`drawio`) and 50 (`citations`). Pick a value after the plugins whose output you need: a plugin that reads tables made by Dataview runs after 10.

## Guarantees

- The frontmatter is parsed and removed before `process_markdown` runs.
- Plugins run before embeds, callouts, wiki links and image captions, so their output passes the rest of the pipeline like written Markdown.
- Plugins also run on embedded notes, with the context of the embedded note.
- Keep code as written. Wrap a rewrite in `outside_code` from `obsidian_pdf_exporter.core.code`, as Obsidian does not process code.

## In this repository

A plugin for a broadly used Obsidian plugin can go into `obsidian_pdf_exporter/plugins/<name>/` with an `__init__.py` that exports the class and a thin `plugin.py`. Put larger parsing code in a module next to it, as Dataview does with `engine.py`. Add the entry point to the project's `pyproject.toml`, unit tests in `tests/unit/`, a page in these docs and an example in `examples/`.
