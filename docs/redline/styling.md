---
title: Styling the redline
description: The built-in redline template, the elements and classes a redline emits, and how to restyle them in any template.
---

# Styling the redline

`ope redline` uses the built-in `redline` template unless `-T` names another one. It has the layout of `default` (A4, header and footer, title block, table of contents) and adds the styles for the marks.

!!! note "Current design"
    The pictures in this section show the current look of the `redline` template. A new design is being worked on, so the colours and boxes may change. The elements and classes below are what a template styles.

## What a redline emits

On top of the HTML of a normal export, a redline has:

| Element or selector | What it is |
| ------------------- | ---------- |
| `ins` | Inserted words inside a changed block, also in a heading and in the table of contents (`nav#TOC ins`). |
| `del` | Removed words inside a changed block. `~~strikethrough~~` in the notes is also a `del`. |
| `div.redline-ins` | A block that is only in the newer version: a paragraph, a list, a heading, a table. |
| `div.redline-del` | A block that is only in the older version. A heading inside it is turned into `strong`, so it gets no number and stays out of the table of contents. |
| `header#title-block-header .subtitle` | The subtitle, by default `Redline: <from> -> <to>`. |

Figures and tables are not moved to landscape pages in a redline. WeasyPrint supports `:has()`, so a paragraph or list item that holds a change can be styled too, for example `p:has(ins, del)`.

The colours of the `redline` template are custom properties on `:root`: `--color-ins-bg`, `--color-ins-text`, `--color-del-bg` and `--color-del-text`. The full CSS is [`redline.css`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/templates/builtin/redline/redline.css).

## Restyle the redline

Start from a copy of `redline.css`, change or add rules at the end, and pass the file with `-T`:

```bash
curl -sL -o my-redline.css https://raw.githubusercontent.com/Spenhouet/obsidian-pdf-exporter/main/obsidian_pdf_exporter/templates/builtin/redline/redline.css
cat >> my-redline.css <<'CSS'
:root { --color-ins-text: #0b4f9c; --color-ins-bg: #e3eefb; }
p:has(ins, del) { border-left: 2pt solid #6b46c1; margin-left: -5mm; padding-left: 4mm; }
CSS
ope redline ./Policy --from-commit v1.0.0 -T ./my-redline.css
```

A single CSS file or a [template folder](../templating/folders.md) does not get the header and footer of `redline`, which come from Python. Write them in `page.css` as described in [Header and footer](../templating/header-footer.md), or keep them by subclassing `RedlineTemplate` in a [Python template](../templating/python.md#extend-a-built-in-template) and adding CSS in `get_css()`.

## Redline styles in your own template

Any template can be used for a redline, for example a letterhead made for `ope export`. Such a template has no styles for the marks, so `ins` and `del` only get the browser defaults (underline and strike-through) and the blocks have no colour. Add rules like these:

```css
ins { background: #e6ffed; color: #08611a; text-decoration: underline; }
del { background: #ffeef0; color: #b31d28; text-decoration: line-through; }
.redline-ins, .redline-del { border-left: 4px solid; padding: 0.6em 1em; margin: 0.8em 0; }
.redline-ins { background: #e6ffed; border-color: #2ea44f; }
.redline-del { background: #ffeef0; border-color: #cb2431; text-decoration: line-through; }
```

```bash
ope redline ./Handbook --from-commit v1.0.0 -T ./letterhead/
```

To check what was emitted, run with `--debug` and open `redline_final.html` in the build folder next to the PDF.
