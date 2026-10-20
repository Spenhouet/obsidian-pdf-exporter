---
title: Warnings
description: Every warning ope prints, and which ones mean that content is missing from the PDF.
---

# Warnings

An export never stops for a problem in a note. It keeps what it cannot render in a simple form and prints a line that starts with `Warning:`. The text of a warning is never written into the PDF.

The lines go to standard output, between the progress lines:

```text
Building PDF: Handbook
  ...
  Warning: could not resolve embed ![[Old spec#^scope]] in Handbook/Scope.md
  Warning: Link to note outside the PDF: "Release plan#Dates" in Handbook/Overview.md, kept as text
  1 link to 1 target outside the PDF kept as text (see the warnings above)
```

In the tables below, `<target>` is the text inside the brackets, `<page>` the note the problem is in (a path in the vault) and `<file>` a file name. The messages start with these words exactly, so a script can sort them with `grep`.

## Links outside the PDF

These links point to a note, heading or block that is not part of the export. Nothing is missing: the text of the link is in the PDF as plain text, it only cannot be clicked. See [Links to pages outside the PDF](../obsidian/wiki-links.md#links-to-pages-outside-the-pdf).

| Message | Meaning |
| ------- | ------- |
| `Link to note outside the PDF: "<target>" in <page>, kept as text` | A wiki link, Markdown link, Dataview or Bases link, or the link an embed falls back to, names a note that is outside the exported folder or does not exist. |
| `Link to heading outside the PDF: "#<id>", kept as text` | A link to a heading or block that is not in the PDF, found after pandoc, for example `[[#Typo]]` or a heading a redline left out. |

At the end of the export, one line counts them: `<n> links to <m> targets outside the PDF kept as text (see the warnings above)`.

To list only the problems that are not links outside the PDF:

```bash
ope export ./Vault/Handbook 2>&1 | grep "Warning:" | grep -v "outside the PDF:"
```

## Missing content

Something the note asks for is not in the PDF. The place shows a short placeholder in italics (the target, or _[Image: name]_) or a link instead.

| Message | Meaning |
| ------- | ------- |
| `could not resolve embed ![[<target>]] in <page>` | The embedded note does not exist. |
| `could not find '#<fragment>' for embed ![[<target>]] in <page>` | The note exists, but not the heading or block. |
| `skipped recursive embed ![[<target>]] in <page>` | The embed would include itself again. |
| `embed ![[<target>]] in <page> nests deeper than 10` | Embeds inside embeds go more than 10 levels deep. |
| `could not find image ![[<target>]] in <page>`, `could not find image ![alt](<path>) in <page>`, `could not find image <img src="<path>"> in <page>` | The image file does not exist. |
| `cannot render embed ![[<target>]] (<suffix> files are not rendered) in <page>` | An embed of a file type ope does not draw, such as a canvas. With `, kept as a link` the file is part of the PDF and the embed links to it. |
| `could not find PDF ![[<target>]] in <page>` | The PDF file does not exist. |
| `could not render PDF embed ![[<target>]] (<reason>) in <page>` | The PDF cannot be opened, for example because it is encrypted. |
| `PDF embed ![[<target>]] asks for pages that <file> does not have in <page>` | The page range is outside the PDF. |
| `PDF embed ![[<target>]] shows <n> of its pages; set -O pdf_embeds.max_pages to show more in <page>` | Only the first pages are drawn. |
| `cannot read drawing <file>: <reason>`, `cannot load image <url> in drawing <file>`, `cannot draw embedded file <file> in drawing <file>`, `cannot draw LaTeX equations in drawing <file>, left out` | Excalidraw: the drawing or a part of it is left out. These messages end with `(embedded in <page>)`. |
| `base <file> in <page> can not be read: <reason>` | A Bases file that cannot be parsed. |
| `<n> citation(s) such as [@<key>] are kept as text: no bibliography found. ...`, `cannot read bibliography <path>: <reason>; citations kept as text`, `citation @<key> is not in the bibliography` | Citations stay as `[@key]`. |
| `Page <n> ("<heading>") has <script> text that no installed font can draw, for example "<text>".` | The letters show as boxes, see [Installation](../getting-started/installation.md). |

## Shown in a simpler form

The content is in the PDF, but not drawn the way Obsidian shows it.

| Message | Meaning |
| ------- | ------- |
| `cannot render the <lang> code block in <page>, kept as code` | A code block of a plugin ope does not support. |
| `cannot parse a Dataview query in <page>`, `a Dataview query failed (<reason>) in <page>`, `cannot parse an inline Dataview query in <page>`, `an inline Dataview query failed (<reason>) in <page>`, `a DataviewJS block failed (<reason>) in <page>`, `an inline DataviewJS query failed (<reason>) in <page>` | The query stays as code. Other Dataview messages, such as a CALENDAR value that is not a date, also end with `in <page>`. |
| `<n> Mermaid block(s) could not be drawn and stay as code.`, `Pele could not draw a <kind> diagram: <reason>` | Mermaid diagrams that stay as code. |
| `no installed font has these characters of Mermaid labels: ...` | Some labels show a placeholder character. |
| `could not render math '<tex>': <reason>`, `ziamath is not installed, math is shown as source` | The formula shows as TeX source. |
| `<<tag>> in <page> has no closing tag, kept as text` | Stray HTML is shown as text. |
| `cannot show only #<fragment> of drawing ![[<target>]], showing the whole drawing` | Excalidraw: the whole drawing instead of a part. |
| `base <file> in <page> ...` (other messages) | A Bases view, filter, sort or formula that is ignored or shown as a table. |
| `ignored '#<fragment>' in PDF embed ![[<target>]] in <page>` | An unknown PDF fragment; all pages are drawn. |

## Settings

| Message | Meaning |
| ------- | ------- |
| `unknown tables.landscape=...`, `tables.landscape_min_cols=... is not a positive number, using 6`, `unknown footnotes=...` | An `-O` value is not known; the default is used. |
| `-O <option> has no effect. ...` | A Mermaid option of older versions. |
| `--blame needs a git repository; the PDF has no blame strip` | `--blame` outside a git repository. |
| `bibliography <path> from <origin> does not exist`, `bibliography <path> is not one of <formats>, skipped`, `citation style <path> does not exist, using the default style` | Citation settings. |
