---
title: Python templates
description: The Template class, ExportContext and Decorations, hooks for Markdown and HTML, and how to register and publish a template.
---

# Python templates

A Python template can do what a folder cannot: build the header and footer from the title, version or `-O` options, extend a built-in template instead of copying its CSS, and change the Markdown or HTML of the document.

## The `Template` class

```python
from obsidian_pdf_exporter.templates import Decorations, ExportContext, Template


class MyTemplate(Template):
    name = "mytemplate"                  # the --template name, must be unique
    description = "Shown by list-templates"

    def get_css(self) -> str: ...                                   # required in practice
    def assets(self) -> dict[str, bytes]: return {}                 # name -> bytes
    def decorations(self, context: ExportContext) -> Decorations | None: return None
    def mermaid_config(self, context: ExportContext) -> dict[str, object]: return {}
    def process_markdown(self, content: str, context: ExportContext) -> str: return content
    def process_html(self, html: str, context: ExportContext) -> str: return html
```

| Member | Called | Notes |
| ------ | ------ | ----- |
| `name` | | Identifier for `--template`. |
| `description` | | One line for `list-templates`. |
| `get_css()` | Before the export, without context | The CSS source. Written to `<build>/<name>.css`. |
| `assets()` | Before the export | Files written into the build folder, for relative `url(...)` in the CSS. |
| `decorations(ctx)` | After the HTML hooks | Running header and footer HTML and page CSS. `None` for none. |
| `mermaid_config(ctx)` | Before Mermaid runs | Base Mermaid config. `-O mermaid.config` is merged over it. |
| `process_markdown(content, ctx)` | Right before pandoc | The assembled Markdown of the whole document, after all steps and plugins. |
| `process_html(html, ctx)` | After pandoc and the HTML steps | The full HTML document, before decorations. |

One instance is made per export. Do not keep state on the class.

`get_css()` has no context. Anything that depends on the title or `-O` options goes into `decorations`, `process_markdown` or `process_html`.

## `ExportContext`

```python
@dataclass
class ExportContext:
    title: str                 # --title or the folder name
    subtitle: str = ""         # --subtitle
    version: str = ""          # --version (export only)
    date: str = ""             # --date or today, ISO
    label: str = ""            # version, short commit hash, "Redline: a -> b" or empty
    output_path: Path          # the PDF
    build_dir: Path            # the build folder, for scratch files
    options: dict[str, str]    # the -O key=value pairs

    @property
    def formatted_date(self) -> str: ...   # "7 May, 2026" for an ISO date
```

Treat it as read-only.

## `Decorations`

```python
@dataclass
class Decorations:
    running_html: str = ""     # put right after <body>
    page_css: str = ""         # put into <head>
```

The mechanics are described in [Header and footer](header-footer.md). Strings from the context must be escaped: HTML escaping for `running_html`, CSS string escaping for `content: "..."`.

## Extend a built-in template

Subclass `DefaultTemplate` to keep its CSS, header and footer and add to them. This template adds a confidentiality label from `-O confidentiality=...`:

```python title="confidential.py"
--8<-- "examples/_templates/confidential.py"
```

The result is in the [recipes](recipes.md#confidentiality-label).

## Change Markdown or HTML

Use these hooks only when CSS cannot do it:

```python
def process_markdown(self, content: str, context: ExportContext) -> str:
    if context.options.get("draft") == "yes":
        return "::: {.draft-banner}\nDraft, not approved\n:::\n\n" + content
    return content

def process_html(self, html: str, context: ExportContext) -> str:
    return html.replace('class="title"', 'class="title brand-title"')
```

`process_markdown` gets the Markdown after the steps and plugins: Dataview tables and Meta Bind values are already in place. Decorations are added after `process_html`, so it cannot change them. If the syntax of the notes is the problem, write a [plugin](../plugins/write-a-plugin.md) instead.

## Assets

```python
from importlib import resources
from pathlib import Path

from obsidian_pdf_exporter.templates.base import asset_data_uri


def assets(self) -> dict[str, bytes]:
    return {"logo.svg": (resources.files(__package__) / "logo.svg").read_bytes()}

# For an image in running_html, a data URI avoids WeasyPrint's URL rules in margin boxes:
logo = asset_data_uri(Path(__file__).with_name("logo.svg"))
running_html = f'<img class="brand-logo" src="{logo}">'
```

## Publish as a package

Register the class under the entry point group `obsidian_pdf_exporter.templates`:

```toml title="pyproject.toml"
[project]
name = "acme-pdf-template"
dependencies = ["obsidian-pdf-exporter"]

[project.entry-points."obsidian_pdf_exporter.templates"]
confidential = "acme_pdf_template:ConfidentialTemplate"
```

```bash
uv tool install obsidian-pdf-exporter --with acme-pdf-template   # or with a local path
ope list-templates
ope export ./Vault -T confidential -O confidentiality=Internal
```

## Register at runtime

When ope is used as a library:

```python
from obsidian_pdf_exporter.main import app
from obsidian_pdf_exporter.templates import register_template

register_template(MyTemplate)               # under MyTemplate.name
register_template(MyTemplate, name="alt")   # or another name
app(["export", "./Vault", "-T", "mytemplate"], standalone_mode=False)
```

Runtime templates win over entry points of the same name. This is how the docs screenshots of the confidentiality recipe are made, see `scripts/render_examples.py`.

## Options

`-O key=value` reaches the template as `context.options`. By convention a template uses `<template>.<key>` for its own options and a bare key for options shared with plugins.

A template is Python code and can do anything Python can. Review third-party templates like any other dependency.
