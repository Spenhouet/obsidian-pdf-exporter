# Markdown features

Anything pandoc's GFM dialect understands works as-is. Obsidian-specific features are handled too:

| Feature                                      | What happens                                                                                                                                                                                                    |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[[Page]]`, `[[Page#section\|alias]]`        | Resolved to an in-document anchor if the page exists in the tree, otherwise rendered as italic text.                                                                                                            |
| `![[image.png]]`, `![[image.png\|alt text]]`     | Resolved against the vault index by filename. When several files share a name, the one with the deepest common ancestor with the referencing page wins. SVGs are inlined.                                       |
| `![[Note]]`                                      | Embeds the whole note without its frontmatter. See [Note embeds](#note-embeds).                                                                                                                                 |
| `![[Note#Heading]]`                              | Embeds the heading and its content up to the next heading of the same or a higher level. `![[Note#A#B]]` picks heading `B` inside section `A`.                                                                  |
| `![[Note#^id]]`                                  | Embeds the block marked `^id`: a paragraph, list item or heading whose line ends in ` ^id`, or the block (table, list, quote, callout) directly above a line holding only `^id`.                                |
| `![[Note#^id-id]]`                               | Embeds a [Block Link Plus](https://github.com/Jasper-1024/block-link-plus) range: from the block marked `^id` to the block or line marked `^id-id`. Handled by the `block_link_plus` plugin.                    |
| Block IDs `^id`, `^id-id`                        | Removed from the output.                                                                                                                                                                                        |
| Comments `%% … %%`                               | Stripped (outside code).                                                                                                                                                                                        |
| `![[image.png\|430]]`, `![[image.png\|430x200]]` | Width (and height) in pixels, as in Obsidian. A caption can come first: `![[image.png\|caption\|430]]`.                                                                                                     |
| `> [!note] Title …` callouts                 | Converted to fenced divs. Blank `>` lines stay inside the callout, nested callouts and the foldable markers `[!note]+` / `[!note]-` work (the callout is always shown open). See [Callouts](#callouts). |
| Inline `> [!note] text` (single line)        | Converted to an inline `<span class="callout …">` when it is not at the start of a line (for example inside a table cell).                                                                                     |
| `[[#Heading]]`, `[[#Heading\|alias]]`        | Linked to the heading on the same page. When several pages share a heading name, the one on the linking page wins.                                                                                             |
| Line breaks                                  | A single newline is a line break, as in Obsidian, unless "Strict line breaks" is on in the vault (`strictLineBreaks` in `.obsidian/app.json`). Override with `-O line_breaks=hard` or `-O line_breaks=soft`. |
| Lists right after a paragraph                | Recognized without a blank line in between.                                                                                                                                                                     |
| `==highlight==`                              | Rendered as `<mark>`.                                                                                                                                                                                           |
| `- [ ] task`, `- [x] done`                   | Rendered as ☐ / ☑ on the same line as the text, in a `ul.task-list` without bullets.                                                                                                                           |
| `$...$`, `$$...$$` math                      | Rendered to SVG with [ziamath](https://github.com/cdelker/ziamath) (no TeX needed). Display math is centered. A formula takes the color of the text around it, for example inside a callout. A formula that fails to render is shown as code and the export prints a warning. |
| Footnotes `[^1]`, `^[inline]`                | Shown at the bottom of the page that references them, numbered through the whole document. See [Footnotes](#footnotes). |
| Headings                                     | Each page's headings nest under the page heading. Skipped levels (a page starting with `###`) are closed, so section numbers never contain `0`.                                                                 |
| Tables                                       | Columns are sized by their content, as in Obsidian, also for tables with long source lines. Set widths (an HTML `<colgroup>`) keep their ratio. A very narrow column, such as an image column, is widened to half of an equal share, at most 20%.                                                                                                                    |
| draw.io SVGs                                 | HTML labels are turned into SVG text and the "Text is not SVG - cannot display" note is removed by the `drawio` plugin. See [draw.io diagrams](#drawio-diagrams).                                              |
| YAML frontmatter                             | Parsed (used by Meta Bind) and stripped before rendering.                                                                                                                                                       |
| HTML comments `<!-- … -->`                   | Stripped.                                                                                                                                                                                                       |
| Wide tables                                  | Tables that need more width than a portrait page has are rendered on landscape pages. See [Wide tables](#wide-tables).                                                                                         |
| Code blocks and inline code                  | Shown as written. Links, embeds, block IDs and `%%` comments inside code are not processed, as in Obsidian.                                                                                                     |
| Image followed by a single italic line       | The italic line is promoted to the image's caption.                                                                                                                                                             |
| `![[Books.base]]`, `![[Books.base#View]]`, ` ```base ` blocks | [Obsidian Bases](https://help.obsidian.md/bases) rendered as static tables and lists. See [Bases](#bases). |
| `![[Drawing.excalidraw]]` | [Excalidraw](https://github.com/zsviczian/obsidian-excalidraw-plugin) drawing as an image: the plugin's auto-export SVG or PNG if there is one, otherwise drawn from the scene. Handled by the `excalidraw` plugin. See [Excalidraw drawings](#excalidraw-drawings). |
| ` ```mermaid ` code blocks                   | Rendered to an SVG (or PNG) diagram with mermaid-cli. See [Mermaid diagrams](#mermaid-diagrams).                                                                                                                |

## Content that is not rendered

Some content can not be drawn in a PDF, or is not supported yet. It stays in the document in a simple form, and the export prints a line starting with `Warning:` that names the page:

- An embed of a file type other than notes and images, such as `![[Board.canvas]]`, `![[Manual.pdf]]` or a video, becomes a link (or italic text when the file is not part of the export).
- An image that can not be found becomes the italic text _[Image: name]_.
- A code block of a plugin that the exporter does not render, such as ` ```tasks `, ` ```dataviewjs `, ` ```chart ` or an Admonition block ` ```ad-note `, stays a code block.
- DataviewJS and `TASK` queries become a short note in italics.

## Callouts

Every callout type works. The known types get the class of their style group, plus their own name for aliases (`[!caution]` becomes `callout callout-warning callout-caution`). Any other type, such as `[!information]`, gets `callout callout-information callout-note`, so it looks like a note unless the template styles it. The div also carries `data-callout="<type>"`, and the title is a `span.callout-title`.

## Wide tables

A table goes to its own landscape page when it has at least 6 columns and its content does not fit the portrait width. The exporter estimates the width from the text: each column counts with its longest cell (at most 25 characters, because longer text wraps) or with its longest word, which can not wrap. Images count as a full cell. A table of short values, such as keys and numbers, stays in the text.

Options (`-O key=value`):

| Option                          | Effect                                                              | Default |
| ------------------------------- | ------------------------------------------------------------------- | ------- |
| `tables.landscape=auto\|on\|off` | `auto` uses the width estimate. `on` turns every table with enough columns to landscape. `off` keeps all tables on portrait pages. | `auto`  |
| `tables.landscape_min_cols=N`   | Fewest columns a table needs to go to landscape.                    | `6`     |

```bash
ope export ./Notes -O tables.landscape=off
```

## draw.io diagrams

draw.io stores labels as HTML in `<foreignObject>`, which WeasyPrint does not draw. The exporter replaces each label with SVG `<text>`, one line per `<tspan>`. This is a best effort:

- Mixed formatting inside one label (a bold word, a second color) is flattened to the label's main style.
- Labels with word wrap are wrapped again with an estimated character width, so line breaks can differ a little from draw.io.
- For full fidelity, export the diagram from draw.io with "Convert labels to SVG" turned on, or as PNG.

## Bases

[Bases](https://help.obsidian.md/bases) is a core plugin of Obsidian. A base is a `.base` file (or a ` ```base ` code block) in YAML that selects files with filters and shows them in views. The export renders a view as it looks when the PDF is made:

- `![[Books.base]]` and ` ```base ` blocks show the first view, `![[Books.base#Reading list]]` the view with that name.
- `table` and `cards` views become a table, `list` views a bullet list. Other view types (`kanban`, `map`, views of community plugins) become a table and the export prints a warning.
- Columns come from the view's `order` (just the file name when there is none), with the `displayName` from `properties` as header.
- The file name column links to the note when the note is part of the export.
- `sort` (several properties, `ASC` / `DESC`; empty values last), `limit`, `groupBy` (each group gets a label line and its own table), `groupOrder` and the view's `summaries` (a last row with, for example, `Sum: 25.5`) work.
- The global `filters` and the view's `filters` both apply. `and`, `or` and `not` can be nested. `this` is the note that shows the base.

The expression language of filters and formulas is supported to this extent:

| Area | Supported |
| ---- | --------- |
| Literals | numbers, `"text"` and `'text'`, `true`, `false`, `null`, lists `[1, 2]`, objects, regular expressions `/a.c/gi` |
| Operators | `+ - * / %`, `== != > < >= <=`, `&& \|\| !`, `a ? b : c`, parentheses, `x.y`, `x["y"]`, `list[0]` |
| Properties | `price`, `note.price`, `note["my price"]`, `formula.name`, `file.*`, `this.*`. A name with a `-`, such as `due-date`, is a property when the note has one, otherwise a subtraction. |
| File fields | `name`, `basename`, `path`, `folder`, `ext`, `size`, `ctime`, `mtime`, `properties`, `tags`, `links`, `embeds`, `backlinks` |
| File functions | `hasTag()` (nested tags count), `inFolder()`, `hasLink()`, `hasProperty()`, `asLink()` |
| Global functions | `if()`, `date()`, `duration()`, `now()`, `today()`, `number()`, `list()`, `link()`, `file()`, `min()`, `max()`, `escapeHTML()`, `image()` |
| Any value | `isTruthy()`, `isType()`, `isEmpty()`, `toString()` |
| Text | `length`, `contains()`, `containsAll()`, `containsAny()`, `startsWith()`, `endsWith()`, `lower()`, `title()`, `trim()`, `replace()` (text or regular expression, `$1`), `repeat()`, `reverse()`, `slice()`, `split()` |
| Numbers | `abs()`, `ceil()`, `floor()`, `round()`, `toFixed()` |
| Lists | `length`, `contains()`, `containsAll()`, `containsAny()`, `filter()`, `map()`, `reduce()` (with `value`, `index`, `acc`), `flat()`, `join()`, `reverse()`, `slice()`, `sort()`, `unique()`, `mean()`, `sum()`, `min()`, `max()` |
| Dates | `year`, `month`, `day`, `hour`, `minute`, `second`, `millisecond`, `date()`, `format()` (Moment.js tokens), `time()`, `relative()`, `date + "1M"`, `date - "2h"`, `date - date` (milliseconds) |
| Links | `asFile()`, `linksTo()`, comparing links with files and `this` |
| Objects | `keys()`, `values()` |
| Regular expressions | `matches()` |
| Summaries | `Average`, `Min`, `Max`, `Sum`, `Range`, `Median`, `Stddev`, `Earliest`, `Latest`, `Checked`, `Unchecked`, `Empty`, `Filled`, `Unique`, and custom summaries from the base's `summaries` with `values` |

Anything else, such as `html()`, `icon()`, `random()` or a function that does not exist, is not dropped silently. The export prints a warning that names the base and the expression. A filter that can not be evaluated is ignored, so the view shows more files rather than fewer, and a column that can not be evaluated stays empty. Property types come from the YAML (a date written as `2024-05-01` is a date); the property types set in Obsidian (`.obsidian/types.json`) are not read. Dates are shown as `YYYY-MM-DD`, checkboxes as ☑ / ☐.

## Excalidraw drawings

The `excalidraw` plugin turns embeds of [Excalidraw](https://github.com/zsviczian/obsidian-excalidraw-plugin) drawings into images:

- `![[Drawing.excalidraw]]` or `![[Drawing.excalidraw.md]]`: the drawing note `Drawing.excalidraw.md`.
- `![[Drawing]]`: any note with `excalidraw-plugin` in its frontmatter.
- `![[Sketch.excalidraw]]`: a plain `.excalidraw` JSON file, as saved by excalidraw.com.
- A width works as for images: `![[Drawing.excalidraw|400]]`.

When the plugin's "Auto-export SVG" or "Auto-export PNG" setting wrote `Drawing.excalidraw.svg` (or `.light.svg`, `.png`, `.light.png`) next to the drawing, that file is used as it is. It looks exactly like the drawing in Obsidian. Turn this off with `-O excalidraw.auto_export=off`.

Otherwise the exporter reads the scene from the `## Drawing` section of the note (a ` ```json ` block, or a ` ```compressed-json ` block in LZ-String base64) and draws it as SVG. The hand-drawn look of Excalidraw comes from rough.js in the browser. The exporter draws the same shapes with clean strokes instead, so the PDF needs neither Node.js nor a browser:

| Drawn                                                               | Not drawn (with a warning)                            |
| ------------------------------------------------------------------- | ----------------------------------------------------- |
| Rectangles (with rounded corners), diamonds, ellipses               | Embedded web pages, which become an outlined box with their link |
| Solid fills, and hachure, cross-hatch and zigzag fills as straight hatching | LaTeX equations                               |
| Lines, curves, elbow arrows and all arrowheads                      | Embedded notes, PDFs and drawings inside a drawing    |
| Free drawing, as a line of even width                               | Image cropping (the whole image is drawn)             |
| Text, also inside shapes and on arrows                              | Element links and `#^group=` / `#^area=` / `#^frame=` parts of an embed (the whole drawing is shown) |
| Images from the vault or from a data URL, mirrored images           |                                                       |
| Stroke color, width, dashed and dotted strokes, opacity, rotation   |                                                       |

Frames are not drawn, as in an Excalidraw export. Text uses the Excalidraw fonts when they are installed and falls back to a sans-serif (hand-drawn fonts), sans-serif or monospace font. The frontmatter keys `excalidraw-export-transparent` and `excalidraw-export-padding` are honored. Dark drawings are drawn with their light colors.

Running Excalidraw's own `exportToSvg` (from `@excalidraw/utils`) would keep the hand-drawn look, but it needs a browser DOM: in Node.js it only works with jsdom and extra stand-ins for browser APIs. For an exact copy, turn on auto-export in the plugin.

## Mermaid diagrams

Mermaid code blocks are rendered with [mermaid-cli](https://github.com/mermaid-js/mermaid-cli). The exporter uses `mmdc` if it is on the `PATH`, otherwise `npx -y @mermaid-js/mermaid-cli@11.4.2` if Node.js is installed. Without either, the blocks stay as code blocks and the export prints a warning. A block that fails to render also stays as code.

The default output is SVG, so text stays sharp and searchable. Mermaid normally puts labels in HTML `<foreignObject>` elements, which WeasyPrint does not draw. For SVG output the exporter therefore always sets `htmlLabels: false`. Use PNG if a diagram type needs HTML labels.

Options (`-O key=value`):

| Option                           | Effect                                                                 | Default |
| -------------------------------- | ---------------------------------------------------------------------- | ------- |
| `mermaid=off`                    | Keep Mermaid blocks as code.                                           | on      |
| `mermaid.format=svg\|png`        | Output format.                                                         | `svg`   |
| `mermaid.scale=N`                | Pixel density for PNG output. The image keeps its natural size.        | `3`     |
| `mermaid.config=PATH`            | JSON [Mermaid config](https://mermaid.js.org/config/schema-docs/config.html) (`theme`, `themeVariables`, ...). | none |
| `mermaid.theme=NAME`             | Shortcut for the `theme` key (`default`, `neutral`, `dark`, `forest`, `base`). | none |
| `mermaid.cli=COMMAND`            | Command that runs mermaid-cli, e.g. `"npx -y @mermaid-js/mermaid-cli@11.4.2"`. | auto |
| `mermaid.puppeteer_config=PATH`  | Puppeteer config passed to mermaid-cli as `-p`.                        | none    |
| `mermaid.trim=on\|off`           | Trim the empty space around diagrams. See [Diagram size](#diagram-size). | on    |
| `mermaid.max_height=LENGTH`      | Largest height of a diagram, e.g. `10cm`. Taller diagrams are scaled down. | none |
| `mermaid.landscape=on\|off`      | Put wide diagrams on landscape pages. See [Wide diagrams](#wide-diagrams). | on |
| `mermaid.landscape_ratio=R`      | Width to height ratio from which a diagram that has to shrink goes to a landscape page. | `1.4` |
| `mermaid.landscape_min_font=PT`  | Smallest text size, in points, a diagram may shrink to on a portrait page before it goes to a landscape page. | `7` |

A template can set a base config with the `mermaid` key in `template.yaml` or by overriding `Template.mermaid_config()` (see [TEMPLATING.md](TEMPLATING.md)). `mermaid.config` is merged over it, then `mermaid.theme`.

```bash
ope export ./Notes -O mermaid.config=mermaid.json
```

```json
{ "theme": "base", "themeVariables": { "primaryColor": "#e8eef5", "pie1": "#2c5282" } }
```

### Diagram size

A diagram keeps its natural size and only shrinks when it is wider than the page. `-O mermaid.max_height` scales down diagrams that are taller. Any other sizing belongs in the template's CSS, so the notes contain no export settings. Each diagram has a class per type, such as `mermaid-pie` or `mermaid-gantt`. See [Mermaid diagram sizes](TEMPLATING.md#mermaid-diagram-sizes).

`%%` comment lines are allowed in a block. Mermaid ignores them, and the exporter removes them before rendering, so they do not change the diagram.

Mermaid leaves empty space around some diagram types. The exporter trims it, so the size applies to the visible diagram, with a margin of 8px. PNG images are cropped. For SVG, mermaid-cli renders a second, transparent PNG of each diagram to find the visible area, and the exporter shrinks the `viewBox` to it. This second run takes a few seconds; `-O mermaid.trim=off` skips it.

### Wide diagrams

A diagram that is wider than the page shrinks, and so does its text. When that makes it hard to read, the diagram goes to its own landscape page, like a [wide table](#wide-tables). This happens when the diagram has to shrink to fit a portrait page and either

- its width is at least `mermaid.landscape_ratio` times its height (default `1.4`), or
- its text would become smaller than `mermaid.landscape_min_font` points (default `7`).

A diagram only moves when the landscape page shows it larger than the portrait page, so a tall diagram stays where it is. On the landscape page the diagram is sized to fit the page height, with room for a caption. The estimate assumes an A4 page with the default margins and reads the text size from the diagram (Mermaid's default is 16px).

The diagram gets the `landscape` class. Its paragraph or `<figure>` is wrapped in `<div class="wide-table-section landscape-figure">`, the same class as wide tables, so every template that has a landscape page for tables uses it for diagrams too. A short paragraph right below the diagram that starts with a word and a number, such as `Figure 3: Overview`, is taken as its caption and moves along.

```bash
ope export ./Notes -O mermaid.landscape_ratio=2
ope export ./Notes -O mermaid.landscape=off
```

Notes:

- WeasyPrint clips text that is centered inside a semi-transparent group. Gantt axis labels are drawn that way, so the exporter adds `.grid .tick { opacity: 1 }` to the `themeCSS` of SVG diagrams.
- Wrapped labels in timeline diagrams carry a line offset on both the `<text>` element and its first `<tspan>`. Browsers apply only the inner one, WeasyPrint applies both and draws the text one line too low, outside its box. The exporter removes the outer offset in SVG diagrams.
- Flowchart edge labels use the theme's `edgeLabelBackground`. With the `base` theme it is derived from the theme colors and can look purple. Set `themeVariables.edgeLabelBackground` to change it.
- When running as root (for example in a CI container), Chromium needs `--no-sandbox`. The exporter passes it automatically in that case.

## Footnotes

Footnotes work as in Obsidian: a reference `[^1]` with a definition `[^1]: text` anywhere in the note, or an inline note `^[text]`. Each note is shown at the bottom of the page where it is referenced, with CSS [paged media footnotes](https://www.w3.org/TR/css-gcpm-3/#footnotes) (`float: footnote`), which WeasyPrint supports. The numbers run through the whole document.

The labels of each note (and of each embedded note) are kept apart, so `[^1]` on one page never shows the text of `[^1]` on another page. When two references use the same label, each one gets its own copy of the note, with its own number.

A note that holds a list, a table or another block besides paragraphs can not be placed in the text. It stays in the list of notes at the end of the document, with its number.

Options (`-O key=value`):

| Option                 | Effect                                                            | Default |
| ---------------------- | ----------------------------------------------------------------- | ------- |
| `footnotes=page\|end`  | `page` shows notes at the bottom of the page. `end` keeps pandoc's list of notes at the end of the document. | `page` |

For styling, see [Footnotes](TEMPLATING.md#footnotes) in TEMPLATING.md.

## Note embeds

A note embed is replaced with the content it points to. The target is looked up in the whole vault (the folder with `.obsidian`, or else the git repository root), not only in the exported folder. A plain name such as `![[Note]]` picks the closest note with that name, the same way images are found. A path such as `![[Folder/Note#^id]]` is matched against the end of each note's path in the vault.

Embedded content is processed like the note it comes from:

- Obsidian plugin support (Dataview, Meta Bind, ...) runs with the source note's frontmatter and folder.
- Images and wiki links resolve relative to the source note.
- Embeds inside embedded content are expanded too, up to 10 levels deep. An embed that would include itself again is skipped.

Headings inside embedded content are shifted so that the topmost one sits one level below the heading the embed appears under. Without a heading above the embed, the page title counts as that heading. Nested headings keep their relative levels. This keeps the numbered table of contents consistent: a note section embedded under `### Details` starts at level 4, no matter which level it has in its own note.

An embed that stands alone on its line (it may be indented or inside a quote or callout) is inserted as block content. An embed inside other text is inserted inline, with its lines joined.

An embed whose note, heading or block cannot be found is rendered as italic text (for example _Note#^id_), and the export prints a warning.

## Vault-index resolution rules

The whole vault is indexed once at the start of an export. Folders that contain no markdown (typical attachment folders, regardless of name) are pruned from the page tree automatically. `.git`, `.obsidian`, `.vscode` and any dotfile folder are always skipped.

For embedded images: when several files share the same filename, the index picks the one with the deepest common ancestor with the referencing page. This means a `Chapter A/img/logo.png` is preferred over `images/logo.png` for any page inside `Chapter A/`.
