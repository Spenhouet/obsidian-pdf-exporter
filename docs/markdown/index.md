---
title: Markdown
description: The Markdown dialect ope reads, based on pandoc's markdown reader, and how plain Markdown looks in the PDF.
---

# Markdown

The first layer of an export is the Markdown dialect: the pandoc reader and its extensions. It is defined in one place, [`core/dialect.py`](https://github.com/Spenhouet/obsidian-pdf-exporter/blob/main/obsidian_pdf_exporter/core/dialect.py).

## The dialect

The base is pandoc's `markdown` reader with these settings:

| Setting | Why |
| ------- | --- |
| `+raw_html` | HTML in notes is passed through, as in Obsidian. |
| `+lists_without_preceding_blankline` | A list may start right after a paragraph, as in Obsidian. |
| `-raw_tex` | Text like `A\B` stays as written. |
| `--number-sections` | Headings are numbered. |
| `--columns=100000` | Table columns are sized by their content, not by the dash count of the source. |
| `--toc --toc-depth=4` | The table of contents, unless `--no-toc` is set. |

The core syntax steps add what they need on top, for example `mark` for [highlights](../obsidian/highlights-comments.md) and `hard_line_breaks` for [line breaks](../obsidian/line-breaks.md). Math is rendered by a step of its own, see [Math](math.md).

Anything else pandoc's Markdown reader understands works too, for example definition lists, fenced divs (`::: {.note}`) and attributes on headings (`## Title {#my-id}`). Obsidian does not show those, so they are not covered here.

## Pages in this section

| Page | Covers |
| ---- | ------ |
| [Headings and text](text.md) | Headings, emphasis, horizontal rules |
| [Lists](lists.md) | Bullet, numbered and nested lists |
| [Tables](tables.md) | Alignment, column widths, wide tables on landscape pages |
| [Code blocks](code.md) | Fenced code with syntax highlighting |
| [Block quotes](quotes.md) | Quotes and nested quotes |
| [Footnotes](footnotes.md) | Reference and inline footnotes |
| [Links and images](links-images.md) | Markdown links, URLs and images |
| [Inline HTML](html.md) | HTML tags inside notes |
| [Math](math.md) | Inline and display LaTeX math |

The screenshots are made from the notes in [`examples/`](https://github.com/Spenhouet/obsidian-pdf-exporter/tree/main/examples) with the `default` template. The title block, header and footer are hidden so only the feature shows. [Contributing](../contributing.md#documentation) explains how to rebuild them.
