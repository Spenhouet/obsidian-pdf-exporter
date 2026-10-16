---
title: CSS reference
description: Every element and class ope emits that a template can style, the colour variables of the default template, and the base CSS.
---

# CSS reference

The HTML WeasyPrint lays out is pandoc's HTML plus the markup the steps and plugins add. This page lists what a template can style. To see the HTML of a real export, use [`--debug`](debugging.md).

## Order of the CSS

1. The base CSS of ope (`<style id="obsidian-pdf-exporter-base">`), at the start of `<head>`. It holds working defaults for the markup ope adds, so a template does not need rules for it.
2. The template CSS (`get_css()` or the folder's main CSS).
3. The template's `page_css`, if any.

A later rule wins, so a template can restyle everything from the base CSS.

## Colour and font variables of `default`

`default.css` keeps its colours and fonts in custom properties on `:root`. A template that starts from a copy of it can change the look by changing these:

| Variable | Default | Used for |
| -------- | ------- | -------- |
| `--color-accent` | `#2c5282` | Accent, link colour on screen |
| `--color-grey` | `#606872` | Secondary text, header row of tables, section numbers |
| `--color-light-grey` | `#f5f5f5` | Even table rows, code background |
| `--color-mid-grey` | `#e0e2e4` | Borders, rules |
| `--color-dark` | `#1a1a1a` | Body text |
| `--color-link` | `var(--color-accent)` | Links |
| `--font-sans` | `'Arial', 'Helvetica', sans-serif` | Body text, header and footer |
| `--font-mono` | `'Courier New', monospace` | Code |
| `--page-margin` | `20mm` | Defined for templates to reuse. The `@page` rule of `default` sets its margins directly. |

The `redline` template adds `--color-ins-bg`, `--color-ins-text`, `--color-del-bg` and `--color-del-text`.

## Document structure

| Selector | What it is |
| -------- | ---------- |
| `html`, `body` | Base font size and font. `default` uses `html { font-size: 12pt }`. |
| `header#title-block-header` | Title block at the start: `h1.title`, `p.subtitle`, `p.author` (version label and date). |
| `nav#TOC` | Table of contents: nested `ul`, links, `span.toc-section-number`. |
| `h1` ... `h6` | Headings. The top-level sections are `h1`. Each has `data-number` and an `id`. |
| `.header-section-number` | The number in front of a heading. |
| `div.pdf-running-header`, `.pdf-header-title`, `.pdf-header-subtitle` | Running header of the `default` and `redline` templates. |

## Text

| Selector | What it is |
| -------- | ---------- |
| `p`, `strong`, `em`, `del` | Paragraphs and emphasis. In a redline, `del` is also removed text. |
| `mark` | [Highlights](../obsidian/highlights-comments.md). |
| `a` | Links. `a.heading-link` is a `[[#Heading]]` link. `default` prints links in the text colour. |
| `blockquote` | Block quotes. Callouts are not block quotes. |
| `hr` | Horizontal rules. |
| `code`, `pre`, `pre code` | Inline code and code blocks. Highlighting uses pandoc's classes inside `pre code`: `span.kw` (keyword), `span.st` (string), `span.co` (comment), `span.dv` (number), `span.fu` (function) and more. |
| `ul`, `ol`, `li` | Lists. |
| `ul.task-list`, `span.task-checkbox`, `span.task-checkbox.checked` | [Tasks](../obsidian/tasks.md). The boxes are the glyphs ☐ and ☑. |
| `dl`, `dt`, `dd` | Definition lists (pandoc syntax). |

## Tables

| Selector | What it is |
| -------- | ---------- |
| `table`, `thead`, `tbody`, `tr`, `th`, `td` | Tables. `colgroup > col` holds the column widths ope computed. |
| `.wide-table-section` | Wrapper of a table (or diagram) on a landscape page. See [Landscape pages](header-footer.md#landscape-pages). |

Tips:

- Do not put `break-inside: avoid` on `table`. A table that does not fit the rest of a page would then jump to the next page and leave a gap. Put it on `tr`: the table breaks between rows and the header row repeats.
- `td, th { overflow-wrap: break-word }` is in the base CSS, so long words wrap.

## Callouts

| Selector | What it is |
| -------- | ---------- |
| `.callout` | Every callout, a `div` (or a `span` with `display: block` for inline callouts). |
| `.callout-<group>` | The style group: `note`, `abstract`, `info`, `todo`, `tip`, `success`, `question`, `warning`, `failure`, `danger`, `bug`, `example`, `quote`. |
| `.callout-<type>` | The type as written, for aliases: `.callout-caution` next to `.callout-warning`. |
| `[data-callout="<type>"]` | The type as written, as attribute. |
| `.callout-title` | The title, a `span` holding a `strong`. |

```css
.callout-warning { background: #fff8e1; border-left-color: #f59e0b; color: #7a4b00; }
.callout-title { text-transform: uppercase; letter-spacing: 0.03em; }
.callout[data-callout="checklist"] { border-left-color: #2c7a7b; }
```

## Images and diagrams

| Selector | What it is |
| -------- | ---------- |
| `img.doc-image`, `svg.doc-image` | Embedded images. SVG files are inline `svg` elements with the same class. |
| `figure`, `figcaption` | An image with a caption. |
| `figure.pdf-embed`, `img.pdf-embed-page`, `p.pdf-embed-more` | A [PDF embed](../obsidian/embeds.md#pdf): the figure, one image per page and the note about pages left out. The figure may break between pages. A page taller than the text area of a template needs a smaller `max-height` on `img.pdf-embed-page`. |
| `.mermaid`, `.mermaid-<type>` | A rendered [Mermaid](../obsidian/mermaid.md) diagram, such as `.mermaid-flowchart`, `.mermaid-pie`, `.mermaid-gantt`, `.mermaid-sequenceDiagram`. `graph` blocks get `mermaid-flowchart`. The type keeps its case. |
| `.landscape-figure`, `.landscape` | A wide diagram on a landscape page: the wrapper (with `.wide-table-section`) and the diagram. |
| `span.math.inline`, `span.math.display`, `svg.math-svg` | [Math](../markdown/math.md). `.math-source` is a formula that failed and is shown as code. |

### Mermaid diagrams

A rule of the template wins over the size ope sets, because ope gives the size as a rule with zero specificity:

```css
.mermaid-pie   { height: 6cm; width: auto; }
.mermaid-gantt { width: 100%; }
```

A diagram is never wider than the text (`max-width: 100%`). `default` styles images with `img:where(.doc-image)`, so a class rule such as `.mermaid-pie` also wins over its `height: auto`. A template that sets `height` on `img.doc-image` needs a selector that is at least as specific, for example `img.mermaid-pie`.

## Footnotes

Each footnote is a `span.footnote` with `data-footnote-number` at the place of its reference. The base CSS floats it to the footnote area at the bottom of the page:

```css
.footnote { float: footnote; font-size: 0.75rem; line-height: 1.35; font-weight: normal; font-style: normal; }
.footnote::footnote-call { content: attr(data-footnote-number); vertical-align: super; font-size: 0.65rem; line-height: 0; }
.footnote::footnote-marker { content: attr(data-footnote-number) ". "; }
.footnote-paragraph { display: block; }
@page { @footnote { margin-top: 0.8em; padding-top: 0.3em; border-top: 0.5pt solid #999; } }
```

| Selector | What it is |
| -------- | ---------- |
| `.footnote` | The note text, moved to the bottom of the page. |
| `.footnote::footnote-call` | The number in the text. |
| `.footnote::footnote-marker` | The number in front of the note. |
| `@page { @footnote { ... } }` | The footnote area: rule, spacing. |
| `.footnote-paragraph` | Second and later paragraphs of a note. |
| `section.footnotes`, `a.footnote-ref`, `a.footnote-back` | The list of notes at the end, for notes with block content or with `-O footnotes=end`. |

A note takes its style from where it is referenced, so a note referenced in a callout inherits its colour. `default` sets `.footnote { color: var(--color-dark) }`. Use `data-footnote-number`, not `counter(footnote)`: the numbers come from pandoc and run through the whole document, also into the list at the end.

## Redline

| Selector | What it is |
| -------- | ---------- |
| `ins`, `del` | Inserted and removed words inside a changed block. |
| `.redline-ins`, `.redline-del` | Inserted and removed blocks. |

All elements, the colour variables and how to restyle them: [Styling the redline](../redline/styling.md).

## The base CSS

ope adds this before the template CSS. A template can override any of it.

```css
ul.task-list, ol.task-list { list-style: none; }
ul.task-list > li, ol.task-list > li { list-style: none; }
.task-checkbox { display: inline; margin-right: 0.4em; font-family: "DejaVu Sans", sans-serif; }
span.math.display { display: block; text-align: center; margin: 0.6em 0; }
svg.math-svg { display: inline; overflow: visible; }
.math-source code { white-space: pre-wrap; }
td, th { overflow-wrap: break-word; }
.landscape-figure .landscape { margin-left: auto; margin-right: auto; }
figure.pdf-embed { break-inside: auto; page-break-inside: auto; }
img.pdf-embed-page {
  display: block; margin: 0 auto 0.8em; box-sizing: border-box;
  width: auto; height: auto; max-width: 100%; max-height: 22cm;
  border: 0.75pt solid #999; break-inside: avoid;
}
.pdf-embed-more { font-size: 0.85em; color: #666; margin: 0 0 0.3em; }
figure.pdf-embed figcaption { break-before: avoid; page-break-before: avoid; }
```

plus the footnote rules above, and one rule per image width used in the document (`:where(img[width="300"]) { width: 300px; }`), because WeasyPrint ignores the `width` attribute.

## WeasyPrint is not a browser

- Flexbox and grid work only in part. Block layout, simple flex and CSS counters are safe.
- Images cannot be split. An image that does not fit below the current text moves to the next page. Limit its size, for example with `max-height`, to keep it on the page.
- Print media applies: `@media print` rules are used.
- Supported CSS is listed in the [WeasyPrint docs](https://doc.courtbouillon.org/weasyprint/stable/api_reference.html#supported-features).
