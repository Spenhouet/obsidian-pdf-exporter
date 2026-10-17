---
title: Debugging
description: Inspect the Markdown and HTML of an export with --debug, open final.html in a browser and find why a template rule does not apply.
---

# Debugging

## Keep the build folder

```bash
ope export ./Vault --debug -o out/handbook.pdf
```

The build folder stays next to the PDF and is named after it, here `out/_build_handbook/`:

| File | What it is |
| ---- | ---------- |
| `assembled.md` | The Markdown pandoc reads: all pages after the steps, plugins and `process_markdown`. |
| `output.html` | The HTML pandoc wrote. |
| `final.html` | The HTML WeasyPrint lays out: after the HTML steps, `process_html`, the header and footer HTML and the page CSS. |
| `<template>.css` | The template CSS. |
| images, diagrams | Copied and rendered images, assets of the template. |

## Find where something goes wrong

1. The text is wrong or missing: look at `assembled.md`. If the syntax is still there unchanged, no step or plugin handled it. Check the `Warning:` lines of the export.
2. The structure is wrong (a list is a paragraph, a table is text): pandoc read the Markdown differently. Run pandoc on `assembled.md` by hand to try changes.
3. Only the look is wrong: look at `final.html` and the CSS.

## Open final.html in a browser

```bash
xdg-open out/_build_handbook/final.html    # Linux
open out/_build_handbook/final.html        # macOS
start out\_build_handbook\final.html       # Windows
```

The browser's developer tools show which rules apply to an element and which classes it has. A browser does not draw `@page` margin boxes, running elements or footnote areas, and it lays out some things differently from WeasyPrint. Use it to check selectors, not page breaks.

To check page layout, run WeasyPrint on the file directly:

```bash
uv tool run weasyprint out/_build_handbook/final.html test.pdf
```

WeasyPrint prints a warning for each CSS rule it ignores, with the line of the CSS, for example `Ignored 'gap: 1em' at 4:28, invalid value`.

## Check the PDF from the command line

```bash
pdftotext -layout handbook.pdf - | less                    # the text, for searching and diffs
pdftoppm -r 80 -png -f 1 -l 3 handbook.pdf page            # the first three pages as page-1.png ...
pdfinfo handbook.pdf                                        # page count and page size
```

`pdftotext`, `pdftoppm` and `pdfinfo` are part of poppler (`poppler-utils` on Debian and Ubuntu).

## Common problems

| Problem | Cause and fix |
| ------- | ------------- |
| `Multiple CSS files in ...` | A template folder has more than one CSS file. Set `css:` in `template.yaml`. |
| The header and footer are gone | A folder or single-file template replaces `default` completely, header and footer included. Add them in `page.css`, see [Header and footer](header-footer.md). |
| A logo in the header does not show | The image is not an asset of the template, or the path in `src` differs from the asset name. Assets are matched by their exact path, such as `logo.svg` or `../assets/logo.svg`. |
| A `content: "..."` rule breaks the CSS | A quote or backslash in the text is not escaped. |
| Wide tables have other margins | The template changed `@page` but not `@page landscape-page`. |
| A table leaves a big gap | `break-inside: avoid` is set on `table`. Put it on `tr`. |
| An image jumps to the next page | Images cannot be split. Limit the size with `max-height`. |
| A Mermaid block stays code | Pele could not draw it, for example because of a syntax error. The `Warning:` line of the export names the diagram type and the error. |
