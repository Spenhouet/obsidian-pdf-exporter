---
title: Styling the redline
description: The built-in redline template, the classes and CSS variables of the change marks, the summary, the side-by-side layout and collapsed lines, and how to restyle them in any template.
---

# Styling the redline

`ope redline` uses the built-in `redline` template unless `-T` names another one. The template sets the page, the type and the header and footer, like `default`. The change marks, the change summary, the table-of-contents marks, the side-by-side layout and the collapsed lines come from ope itself: their CSS is added before the CSS of the template, so they work with every template and any template can restyle them.

## Colours

The colours are CSS variables on `:root`. Override them in your template:

| Variable | Default | Used for |
| -------- | ------- | -------- |
| `--rl-ins` | `#0b57b0` | Inserted text and blocks |
| `--rl-del` | `#b23a12` | Removed text and blocks |
| `--rl-move` | `#6b3d9a` | Moved text, move labels and the bar of moved rows |
| `--rl-fmt` | `#8a5a00` | Formatting and link changes, level and task labels |
| `--rl-bar` | `#26292d` | Change bars |
| `--rl-ins-bg`, `--rl-del-bg` | light blue, light red | "new" and "removed" marks in the table of contents |
| `--rl-grey`, `--rl-quiet`, `--rl-dark`, `--rl-light`, `--rl-mid` | greys | Labels, collapsed lines, summary |

## What a redline emits

| Element or selector | What it is |
| ------------------- | ---------- |
| `ins`, `del` | Inserted and removed words, also in headings and in the table of contents. `~~strikethrough~~` in the notes is also a `del`. |
| `ins.rl-moved`, `del.rl-moved` | A list item that moved within its list. |
| `span.rl-fmt` | Text whose formatting changed (`data-rl-fmt`, for example `bold added`). |
| `span.rl-link` | A link whose target changed (`data-old-href`, `data-new-href`). |
| `span.rl-level` | Label of a heading whose level changed (`data-old-level`, `data-new-level`). |
| `li.rl-li-task`, `span.rl-task` | A task that was checked or unchecked (`data-rl-task`). |
| `div.rl-block` | A changed block, with `rl-ins`, `rl-del`, `rl-mod` (changed in place), `rl-move-from` or `rl-move-to`, and `data-rl-kind` (`para`, `list`, `table`, `code`, `image`, `callout`, `heading`, `quote`). |
| `div.rl-heading` | A removed heading (a `div`, so it is not numbered), with `data-level`. |
| `h1.rl-ins` … `h6.rl-ins`, `h1.rl-mod` … | An inserted or changed heading. |
| `tr.rl-tr-ins`, `tr.rl-tr-del`, `tr.rl-tr-mod`, `td.rl-col-ins`, `th.rl-col-ins` | Changed table rows and an added column. |
| `li.rl-li-ins`, `li.rl-li-del`, `li.rl-li-mod`, `li.rl-li-move-from`, `li.rl-li-move-to` | Changed list items. |
| `pre.rl-code`, `span.rl-line`, `.rl-line-ins`, `.rl-line-del` | A changed code block, one span per line. |
| `div.rl-hunk` | A group of neighbouring changed blocks; it carries the change bar in the blackline style. |
| `.rl-move-label`, `.rl-img-label` | Labels of moved blocks and of removed or inserted figures. |
| `section.rl-summary` | The change summary (`.rl-tiles`, `table.rl-sections`, `table.rl-commits`). |
| `.rl-toc-mark`, `.rl-toc-mark-new`, `.rl-toc-mark-del`, `li.rl-toc-removed` | Marks in the table of contents. |
| `.rl-ctx`, `li.rl-ctx-item`, `tr.rl-ctx-row` | Collapsed lines (`-O redline.collapse=on`). |
| `body.rl-blackline`, `body.rl-side-by-side`, `body.rl-collapse` | The style and the collapse option, on `body`. |

The side-by-side style puts the text in `table.rl-sbs`, one `tr.rl-sbs-row` per block with `td.rl-sbs-old`, `td.rl-sbs-gutter` and `td.rl-sbs-new`. The row has the kind of change as `rl-sbs-equal`, `rl-sbs-mod`, `rl-sbs-ins`, `rl-sbs-del`, `rl-sbs-move-from`, `rl-sbs-move-to` or `rl-sbs-ctx`; an empty side is `td.rl-empty` with a `div.rl-gap`. Side-by-side pages are landscape: the page size of the template (the last `size` of a plain `@page` rule in its CSS or page CSS) turned on its side, A4 landscape when the template sets none. The rule is added after the template's page CSS, so it also wins over a template that sets a portrait size. Images and drawings in a column are at most as wide as the column.

The full CSS is in [`core/assets/`](https://github.com/Spenhouet/obsidian-pdf-exporter/tree/main/obsidian_pdf_exporter/core/assets). To check what was emitted, run with `--debug` and open `redline_final.html` in the build folder next to the PDF.

## Restyle the redline

Add rules to a template. A single CSS file is enough:

```css title="my-redline.css"
:root { --rl-ins: #006d3c; --rl-del: #a4161a; --rl-bar: #6b46c1; }
ins { text-decoration: underline; }                 /* single instead of double underline */
.rl-blackline .rl-hunk { border-left-width: 3pt; }   /* a thicker change bar */
```

```bash
ope redline ./Policy --from-commit v1.0.0 -T ./my-redline.css
```

A single CSS file or a [template folder](../templating/folders.md) does not get the header and footer of `redline`, which come from Python. Write them in `page.css` as described in [Header and footer](../templating/header-footer.md), or keep them by subclassing `RedlineTemplate` in a [Python template](../templating/python.md#extend-a-built-in-template) and adding CSS in `get_css()`.

Any template made for `ope export`, for example a letterhead, can be used for a redline as it is: the change marks come with ope.

```bash
ope redline ./Handbook --from-commit v1.0.0 -T ./letterhead/
```

## The blame strip

The [blame strip](blame.md) is drawn next to the page after the document is rendered, so templates do not change it. Its look is fixed: one line of grey text per block, darker for blocks changed in the compared range.
