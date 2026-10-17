# ope templates: quick reference

Full docs: https://spenhouet.com/obsidian-pdf-exporter/templating/

## Folder template

```text
my-template/
├── template.yaml
├── main.css       # copy of default.css plus your rules
├── header.html    # running elements (logo, address)
├── page.css       # @page rules, margin boxes
└── logo.svg       # assets: every other file, or list them in template.yaml
```

```yaml
name: my-template          # default: folder name
description: One line for list-templates
css: main.css              # default: template.css or the only *.css
running_html: header.html  # put right after <body>
page_css: page.css         # put into <head>
assets: [logo.svg]         # default: all non-css/yaml/html/md files, plus ../assets/
mermaid: { themeVariables: { fontSize: 14px } }
```

`src="logo.svg"` in header.html and `url(logo.svg)` in page.css become data URIs, so logos work in margin boxes. A sibling `assets/` folder is shared as `../assets/<name>`.

## Header and footer

```css
/* Text from the title block: h1.title, p.subtitle, p.author ("<version> | <date>") */
header#title-block-header .title  { string-set: doc-title content(); }
header#title-block-header .author { string-set: doc-meta content(); }

.logo { position: running(logo); width: 40mm; }   /* <img class="logo"> in header.html */

@page {
  margin: 30mm 20mm 22mm 20mm;
  @top-left     { content: string(doc-title); font-family: Arial, sans-serif; font-size: 8pt; }
  @top-right    { content: element(logo); vertical-align: bottom; }
  @bottom-left  { content: string(doc-meta); font-family: Arial, sans-serif; font-size: 7pt; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font-family: Arial, sans-serif; font-size: 7pt; }
}
@page :first { margin-top: 40mm; }
@page landscape-page { size: A4 landscape; margin: 20mm; }   /* wide tables and diagrams */
.wide-table-section { page: landscape-page; break-before: page; break-after: page; }
```

Margin boxes do not inherit the body font; set it per box.

## What to style

- Variables of default.css: `--color-accent`, `--color-grey`, `--color-light-grey`, `--color-mid-grey`, `--color-dark`, `--color-link`, `--font-sans`, `--font-mono`.
- `header#title-block-header`, `nav#TOC`, `h1`-`h6`, `.header-section-number`
- `table`, `th`, `td`, `tr` (put `break-inside: avoid` on `tr`, never on `table`)
- `.callout`, `.callout-<group>` (note, abstract, info, todo, tip, success, question, warning, failure, danger, bug, example, quote), `.callout-<alias>`, `[data-callout]`, `.callout-title`
- `img.doc-image`, `svg.doc-image`, `figure`, `figcaption`, `.mermaid`, `.mermaid-<type>`
- `mark`, `code`, `pre`, `blockquote`, `ul.task-list`, `.task-checkbox`, `.task-checkbox.checked`
- `.footnote`, `.footnote::footnote-call`, `.footnote::footnote-marker`, `@page { @footnote { } }`
- Redline: `ins`, `del`, `.redline-ins`, `.redline-del` (removed headings become `strong`). How to restyle: https://spenhouet.com/obsidian-pdf-exporter/redline/styling/
- Dark page: `@page { background: #1a202c; }`

## Python template (options, extending default)

```python
from obsidian_pdf_exporter.templates import Decorations, ExportContext
from obsidian_pdf_exporter.templates.builtin.default import DefaultTemplate


class LabelTemplate(DefaultTemplate):
    name = "label"

    def decorations(self, context: ExportContext) -> Decorations | None:
        base = super().decorations(context) or Decorations()
        label = context.options.get("label", "").replace("\\", "\\\\").replace('"', '\\"')
        css = f'@page {{ @top-right {{ content: "{label}"; color: #c53030; font-size: 8pt; }} }}'
        return Decorations(running_html=base.running_html, page_css=base.page_css + css)
```

Register under `[project.entry-points."obsidian_pdf_exporter.templates"]` in a package, install with `uv tool install obsidian-pdf-exporter --with <package>`, run `ope export ... -T label -O label=Internal`. `ExportContext` has `title`, `subtitle`, `version`, `date`, `label`, `formatted_date`, `options`, `build_dir`, `output_path`. Hooks: `get_css()`, `assets()`, `decorations(ctx)`, `mermaid_config(ctx)`, `process_markdown(md, ctx)`, `process_html(html, ctx)`.
