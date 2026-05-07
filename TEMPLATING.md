# Templating

A **template** decides how the PDF _looks_: CSS, running header/footer, page size, margins, paged-media `@page` rules. Templates are independent of the markdown pipeline.

This document covers both the user-facing recipes (no Python required) and the full authoring spec.

## Table of Contents

- [Built-in templates](#built-in-templates)
- [Selecting a template](#selecting-a-template)
- [Custom templates without writing Python](#custom-templates-without-writing-python)
  - [A. Drop-in CSS file](#a-drop-in-css-file)
  - [B. Template directory with manifest](#b-template-directory-with-manifest)
  - [C. Named user-config template](#c-named-user-config-template)
- [What a template is](#what-a-template-is)
- [Pipeline overview](#pipeline-overview)
- [The `Template` class](#the-template-class)
- [The `ExportContext` object](#the-exportcontext-object)
- [Decorations: running header/footer + `@page` rules](#decorations-running-headerfooter--page-rules)
- [Shipping assets (logos, fonts, icons)](#shipping-assets-logos-fonts-icons)
- [Markdown / HTML hooks](#markdown--html-hooks)
- [Registering a template](#registering-a-template)
- [User options](#user-options)
- [CSS conventions](#css-conventions)
- [Reference templates](#reference-templates)
- [Tips and gotchas](#tips-and-gotchas)

## Built-in templates

| Name      | Purpose                                                                                                                                                          |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `default` | Brand-neutral A4 portrait with title-block heading, running document title in the top-left, version + page counter in the bottom-right, date in the bottom-left. |
| `redline` | Same chrome as `default`, plus styled `<ins>` / `<del>` and `.redline-ins` / `.redline-del` block markup. Used implicitly by the `redline` command.              |

## Selecting a template

```bash
obsidian-pdf-exporter export ./vault --template default
obsidian-pdf-exporter list-templates    # what's installed right now
```

The value of `--template` is resolved in this order:

1. If it is an existing path on disk → loaded as a custom template.
2. Otherwise → looked up by name in the registry (built-in → packaged entry-point → user-config directory → runtime).

## Custom templates without writing Python

Most users only need to swap CSS or add a logo and footer. Three no-Python paths cover that:

### A. Drop-in CSS file

```bash
obsidian-pdf-exporter export ./vault --template ./brand.css
```

The filename stem (`brand`) becomes the template name. CSS only — no header/footer HTML, no extra assets.

### B. Template directory with manifest

```text
my-template/
├── template.yaml     # optional; sensible defaults if absent
├── main.css
├── header.html       # optional: appended after <body>
├── page.css          # optional: @page rules + running() positions
└── logo.svg          # optional: copied next to the CSS at render time
```

```yaml
# template.yaml — every key is optional
name: legal-pack
description: Legal cover sheet style
css: main.css # default: template.css or sole *.css
assets: [logo.svg] # default: every non-css/yaml/html sibling
running_html: header.html # appended after <body>
page_css: page.css # @page rules etc.
```

```bash
obsidian-pdf-exporter export ./vault --template ./my-template/
```

### C. Named user-config template

Drop the directory into your user-config folder so it appears in `list-templates` and works by short name from any vault:

```text
~/.config/obsidian-pdf-exporter/templates/
└── legal-pack/
    ├── template.yaml
    └── main.css
```

```bash
obsidian-pdf-exporter export ./vault --template legal-pack
```

The location can be overridden with `OBSIDIAN_PDF_EXPORTER_TEMPLATES_DIR`, or moved by setting `XDG_CONFIG_HOME`.

---

The remainder of this document covers the Python authoring spec: when you need `process_markdown` / `process_html` hooks, custom decorations, or registering a template under an entry-point.

## What a template is

A template is a Python class that subclasses `obsidian_pdf_exporter.templates.Template`. It supplies:

1. **CSS** applied by both pandoc (`--css`) and WeasyPrint at the PDF rendering stage.
2. Optional **running header/footer HTML** plus the `@page` rules that position it.
3. Optional **assets** (logos, fonts) copied next to the CSS at build time.
4. Optional **pre/post hooks** to mutate the assembled markdown or post-pandoc HTML.

Templates are _brand_ concerns. Markdown/Obsidian semantics belong in plugins, not templates.

## Pipeline overview

For a single export, the pipeline executes in this order. The hooks a template can plug into are in **bold**.

```text
walk vault → assemble markdown ─►  template.process_markdown(md, ctx)        ◄── markdown hook
                                  │
                                  ▼
write template.get_css() + assets() to build dir
                                  │
                                  ▼
pandoc(markdown, css) → HTML
                                  │
                                  ▼
post-process (svg inlining, table normalisation, wide-table landscape)
                                  │
                                  ▼
                                  template.process_html(html, ctx)           ◄── HTML hook
                                  │
                                  ▼
inject template.decorations(ctx).running_html + page_css                     ◄── decorations
                                  │
                                  ▼
WeasyPrint → PDF
```

Plugins (`process_markdown` on each `ObsidianPlugin`) run **before** the template's markdown hook, so by the time your template sees the markdown, Dataview tables / Meta Bind values / etc. are already inlined.

## The `Template` class

```python
from obsidian_pdf_exporter.templates import (
    Decorations,
    ExportContext,
    Template,
)

class MyTemplate(Template):
    name = "mytemplate"               # CLI identifier — must be unique
    description = "One-line summary shown by `list-templates`"

    def get_css(self) -> str:
        ...

    def assets(self) -> dict[str, bytes]:
        return {}                     # name → bytes, copied next to the CSS

    def decorations(self, context: ExportContext) -> Decorations | None:
        return None                   # or Decorations(running_html=..., page_css=...)

    def process_markdown(self, content: str, context: ExportContext) -> str:
        return content                # called right before pandoc

    def process_html(self, html: str, context: ExportContext) -> str:
        return html                   # called after pandoc + standard post-processing
```

| Member | Required | Notes |
|---|---|---|
| `name: str` | yes | Identifier passed to `--template`. Must be unique among installed templates. |
| `description: str` | no | Shown by `list-templates`. |
| `get_css() -> str` | yes (in practice) | Returns the CSS source as a string. The exporter writes it to `<build>/<name>.css`. |
| `assets() -> dict[str, bytes]` | no | Each entry is written to `<build>/<key>` as bytes. Reference the file by relative path from the CSS. |
| `decorations(ctx) -> Decorations \| None` | no | Return `None` to skip decorations. |
| `process_markdown(content, ctx) -> str` | no | Mutate the assembled markdown before pandoc runs. |
| `process_html(html, ctx) -> str` | no | Mutate the HTML after pandoc + post-processing, before decorations and PDF rendering. |

A template instance is created **once per export** and discarded; no state survives between runs. Don't keep mutable state on the class.

## The `ExportContext` object

`ExportContext` is the read-only metadata bag passed to `decorations`, `process_markdown`, and `process_html`.

```python
@dataclass
class ExportContext:
    title: str                       # document title (--title or root folder name)
    subtitle: str = ""               # --subtitle
    version: str = ""                # --version (export only)
    date: str = ""                   # ISO date (--date or today)
    label: str = ""                  # short label: version, git short hash, or "Redline: a -> b"
    output_path: Path                # final PDF path
    build_dir: Path                  # working directory; assets are written here
    options: dict[str, str]          # --option key=value pairs

    @property
    def formatted_date(self) -> str: # "7 May, 2026" if `date` is ISO, else passthrough
```

Treat the context as immutable. Don't write files into `output_path.parent` from a template — use `build_dir` for any scratch files (although in practice you should never need to).

## Decorations: running header/footer + `@page` rules

`decorations(ctx)` returns a `Decorations` instance — the only mechanism for putting content in the page margins.

```python
@dataclass
class Decorations:
    running_html: str = ""           # injected immediately after <body>
    page_css: str = ""               # injected into <head>
```

Pattern: declare the running element in `running_html`, position it via `running()` in `page_css`, then reference it from `@page` margin boxes via `element(name)`.

Minimal "title in the top-left, page X / Y in the bottom-right" example:

```python
from obsidian_pdf_exporter.templates import Decorations, ExportContext, Template

class MyTemplate(Template):
    name = "mytemplate"

    def get_css(self) -> str:
        return "body { font-family: sans-serif; }"

    def decorations(self, ctx: ExportContext) -> Decorations:
        running_html = (
            f'<div class="my-header">{_html_escape(ctx.title)}</div>\n'
        )
        page_css = """
        .my-header {
            position: running(my-header);
            font-size: 8pt;
        }
        @page {
            @top-left  { content: element(my-header); }
            @bottom-right {
                content: "Page " counter(page) " / " counter(pages);
                font-size: 7pt;
            }
        }
        """
        return Decorations(running_html=running_html, page_css=page_css)
```

### Escaping rules

- HTML in `running_html` must be valid HTML (escape `&`, `<`, `"`).
- Strings inside CSS `content: "…"` need CSS string escaping: backslash → `\\`, `"` → `\"`, newline → `\A `.

The reference templates ship `_esc_html()` and `_css_str()` helpers — feel free to copy them.

### `@page :first` and other selectors

WeasyPrint supports the [CSS Paged Media](https://www.w3.org/TR/css-page-3/) module, including `@page :first`, `@page :left` / `@page :right`, and named pages. Use them in `page_css` (or `get_css()`) — for example to suppress the running header on the first page:

```css
@page :first {
    @top-left { content: none; }
}
```

### Multiple running elements

Declare each one with its own `position: running(name)` block, then reference each from a different `@page` margin box.

## Shipping assets (logos, fonts, icons)

Override `assets()` to ship binary files alongside your CSS:

```python
def assets(self) -> dict[str, bytes]:
    return {
        "logo.svg": (resources.files(__package__) / "logo.svg").read_bytes(),
    }
```

Each entry lands at `<build_dir>/<key>`. Reference it from CSS with a relative URL:

```css
.brand-logo { background-image: url("logo.svg"); }
```

For SVG logos used inside `running_html`, the pragmatic approach is `asset_data_uri()`:

```python
from obsidian_pdf_exporter.templates.base import asset_data_uri

logo_uri = asset_data_uri(Path(__file__).with_name("logo.svg"))
running_html = f'<img class="brand-logo" src="{logo_uri}" />'
```

That sidesteps WeasyPrint's relative-URL resolution rules, which can be finicky for elements inside page margin boxes.

## Markdown / HTML hooks

Use these only if a CSS-only solution is impossible.

```python
def process_markdown(self, content: str, ctx: ExportContext) -> str:
    # Example: prepend a confidentiality banner.
    if ctx.options.get("confidentiality") == "internal":
        return "::: {.confidential-banner}\nINTERNAL — DO NOT DISTRIBUTE\n:::\n\n" + content
    return content

def process_html(self, html: str, ctx: ExportContext) -> str:
    # Example: rewrite a class on the post-pandoc HTML.
    return html.replace('class="title"', 'class="title brand-title"')
```

The HTML the `process_html` hook receives is already a complete `<!doctype html>` document (pandoc's standalone output) plus the standard post-processing (SVG inlining, empty-`<thead>` removal, colgroup normalisation, wide-table wrapping). Decorations are injected **after** your hook returns, so you cannot remove them from `process_html`.

## Registering a template

### As a Python distribution (recommended)

Declare an entry point in your package's `pyproject.toml`:

```toml
[project.entry-points."obsidian_pdf_exporter.templates"]
mytemplate = "my_pdf_template:MyTemplate"
```

Install the package (`pip install my-pdf-template` or `uv pip install -e .`) and the template appears in `list-templates`.

### At runtime (embedding the library)

If you're embedding `obsidian-pdf-exporter` as a library and don't want to ship a separate distribution:

```python
from obsidian_pdf_exporter.templates import register_template

register_template(MyTemplate)            # uses MyTemplate.name
register_template(MyTemplate, name="alt") # or override the name
```

Runtime-registered templates appear alongside entry-point ones in `list-templates`, and runtime registrations override entry-point ones with the same name.

## User options

The user can pass arbitrary `--option key=value` pairs on the CLI (repeatable). They reach your template via `ExportContext.options` (a plain `dict[str, str]`).

```python
def get_css(self) -> str:
    return self._base_css() + ("\n.brand--dark body { background: #111; }\n"
                                if self._wants_dark() else "")
```

Better practice: keep all option-driven decisions inside `decorations`, `process_markdown`, or `process_html`, where the context is available. `get_css()` cannot see the context — it's called before the export starts.

Suggested naming convention:

| Scope | Key prefix | Example |
|---|---|---|
| Template-private | `<template-name>.<key>` | `mytemplate.layout=compact` |
| Cross-cutting (used by template + plugins) | bare key | `brand=acme` |

This avoids collisions when third-party plugins start consuming options.

## CSS conventions

The exporter relies on a stable set of class names emitted by pandoc + the post-processing steps. To keep your template compatible, style at least these:

| Selector | Purpose |
|---|---|
| `body`, `html` | Base typography. |
| `h1` … `h6` | Headings. `h1` is the document title via pandoc's title block. |
| `header#title-block-header` (`.title`, `.subtitle`, `.date`, `.author`) | Title block — pandoc emits this when the markdown starts with `% Title`. |
| `nav#TOC` | Table of contents. |
| `table`, `thead`, `th`, `td`, `tr:nth-child(even)` | Tables. |
| `pre`, `code`, `pre code` | Code blocks and inline code. |
| `blockquote` | Quotes (note: Obsidian callouts are _not_ blockquotes after conversion). |
| `.callout`, `.callout-note`, `.callout-info`, `.callout-tip`, `.callout-warning`, `.callout-danger`, `.callout-important`, `.callout-example`, `.callout-abstract`, `.callout-todo`, `.callout-success`, `.callout-question`, `.callout-quote` | Obsidian callout types. |
| `.wide-table-section` | Auto-detected wide table block. The exporter sets `page: landscape-page;` and `break-before/after: page;` on this class — your CSS should also declare a `@page landscape-page { size: A4 landscape; … }` rule with appropriate margins. |
| `img.doc-image` | Embedded images (`![[…]]` and standard markdown images). |
| `figure`, `figcaption` | Pandoc emits these when an image has alt text. |
| `.header-section-number`, `nav#TOC .toc-section-number` | Pandoc's auto-numbered headings. |

For the redline pipeline, additionally:

| Selector | Purpose |
|---|---|
| `ins`, `del` | Word-level changes (inline). |
| `.redline-ins`, `.redline-del` | Whole-block insertions / deletions. |

The shipped `default.css` and `redline.css` are full, working examples — copy and adapt rather than starting from scratch.

## Reference templates

Both built-in templates are intentionally small enough to read top-to-bottom:

- [`obsidian_pdf_exporter/templates/builtin/default/template.py`](obsidian_pdf_exporter/templates/builtin/default/template.py)
- [`obsidian_pdf_exporter/templates/builtin/default/default.css`](obsidian_pdf_exporter/templates/builtin/default/default.css)
- [`obsidian_pdf_exporter/templates/builtin/redline/template.py`](obsidian_pdf_exporter/templates/builtin/redline/template.py)
- [`obsidian_pdf_exporter/templates/builtin/redline/redline.css`](obsidian_pdf_exporter/templates/builtin/redline/redline.css)

A typical branded template starts as a copy of `default`, plus:

- a logo in the top-right margin via `running_html` + `element(brand-logo)`,
- a corporate colour in `--color-accent`,
- a confidentiality footer with `content: "{ctx.options.get('confidentiality', '')}"`,
- a `@page :first` rule that suppresses the running header for a cover page.

## Tips and gotchas

- **Keep the template thin.** If you find yourself parsing markdown in `process_markdown`, ask whether it should be a plugin instead. Templates are about appearance.
- **`get_css()` is called before the context exists.** Anything that depends on `ExportContext.options` must live in `decorations`, `process_markdown`, or `process_html`.
- **CSS strings are _not_ Python f-strings.** When you build a `content: "…"` value with an f-string, escape quotes and newlines (use the `_css_str()` helper). Forgetting this is the #1 source of WeasyPrint syntax errors.
- **WeasyPrint != browsers.** Some flexbox/grid features are partial. Stick to block layout, simple flex, and CSS counters for page numbering. Test with `--debug` and inspect `_build_<title>/` to see the exact HTML+CSS handed to WeasyPrint.
- **`@page` margins must be wide enough for your decorations.** If your running header is 20pt tall and your top margin is 25mm, you have ~5mm of margin left for actual page content padding. Either widen the margin or shrink the header.
- **Wide tables go to a named landscape page.** If your template overrides `@page` margins, also override `@page landscape-page` or wide tables will inherit the default landscape margins (which may not match your branding).
- **`process_html` runs before decorations.** You cannot remove or alter `running_html` from `process_html`. To skip decorations conditionally, return `None` from `decorations()`.
- **Branded templates ship as separate distributions.** Don't add a company-specific template to this repository — publish it as `mybrand-pdf-exporter-template` (or similar) and let users install it alongside.
- **Third-party templates can ship arbitrary Python.** A template is just a class with an entry point — it can pull config from environment variables, talk to a remote service, etc. Keep this in mind when reviewing untrusted templates.
