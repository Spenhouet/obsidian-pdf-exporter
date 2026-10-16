# Markdown features

Anything pandoc's GFM dialect understands works as-is. Obsidian-specific features are handled too:

| Feature                                          | What happens                                                                                                                                                                                                    |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[[Page]]`, `[[Page#section\|alias]]`            | Resolved to an in-document anchor if the page exists in the tree, otherwise rendered as italic text.                                                                                                            |
| `![[image.png]]`, `![[image.png\|alt text]]`     | Resolved against the vault index by filename. When several files share a name, the one with the deepest common ancestor with the referencing page wins. SVGs are inlined.                                       |
| `![[Note]]`                                      | Embeds the whole note without its frontmatter. See [Note embeds](#note-embeds).                                                                                                                                 |
| `![[Note#Heading]]`                              | Embeds the heading and its content up to the next heading of the same or a higher level. `![[Note#A#B]]` picks heading `B` inside section `A`.                                                                  |
| `![[Note#^id]]`                                  | Embeds the block marked `^id`: a paragraph, list item or heading whose line ends in ` ^id`, or the block (table, list, quote, callout) directly above a line holding only `^id`.                                |
| `![[Note#^id-id]]`                               | Embeds a [Block Link Plus](https://github.com/Jasper-1024/block-link-plus) range: from the block marked `^id` to the block or line marked `^id-id`.                                                             |
| `![[image.png\|430]]`, `![[image.png\|430x200]]` | Width (and height) in pixels, as in Obsidian. A caption can come first: `![[image.png\|caption\|430]]`.                                                                                                         |
| `> [!note] Title …` callouts                     | Converted to fenced divs with a class per type (`note`, `tip`, `warning`, `danger`, `info`, `important`, `example`, `abstract`, `todo`, `success`/`check`/`done`, `question`/`help`, `failure`/`bug`, `quote`). |
| Inline `> [!note] text` (single line)            | Converted to an inline `<span class="callout …">`.                                                                                                                                                              |
| YAML frontmatter                                 | Parsed (used by Meta Bind) and stripped before rendering.                                                                                                                                                       |
| HTML comments `<!-- … -->`                       | Stripped.                                                                                                                                                                                                       |
| Block IDs `^id`, `^id-id`                        | Removed from the output.                                                                                                                                                                                        |
| Comments `%% … %%`                               | Stripped (outside code blocks).                                                                                                                                                                                 |
| Wide tables                                      | Auto-detected; rendered on landscape pages.                                                                                                                                                                     |
| Image followed by a single italic line           | The italic line is promoted to the image's caption.                                                                                                                                                             |
| ` ```mermaid ` code blocks                       | Rendered to an SVG (or PNG) diagram with mermaid-cli. See [Mermaid diagrams](#mermaid-diagrams).                                                                                                                |

## Mermaid diagrams

Mermaid code blocks are rendered with [mermaid-cli](https://github.com/mermaid-js/mermaid-cli). The exporter uses `mmdc` if it is on the `PATH`, otherwise `npx -y @mermaid-js/mermaid-cli@11.4.2` if Node.js is installed. Without either, the blocks stay as code blocks and the export prints a warning. A block that fails to render also stays as code.

The default output is SVG, so text stays sharp and searchable. Mermaid normally puts labels in HTML `<foreignObject>` elements, which WeasyPrint does not draw. For SVG output the exporter therefore always sets `htmlLabels: false`. Use PNG if a diagram type needs HTML labels.

Options (`-O key=value`):

| Option                          | Effect                                                                                                         | Default |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------- |
| `mermaid=off`                   | Keep Mermaid blocks as code.                                                                                   | on      |
| `mermaid.format=svg\|png`       | Output format.                                                                                                 | `svg`   |
| `mermaid.scale=N`               | Pixel density for PNG output. The image keeps its natural size.                                                | `3`     |
| `mermaid.config=PATH`           | JSON [Mermaid config](https://mermaid.js.org/config/schema-docs/config.html) (`theme`, `themeVariables`, ...). | none    |
| `mermaid.theme=NAME`            | Shortcut for the `theme` key (`default`, `neutral`, `dark`, `forest`, `base`).                                 | none    |
| `mermaid.cli=COMMAND`           | Command that runs mermaid-cli, e.g. `"npx -y @mermaid-js/mermaid-cli@11.4.2"`.                                 | auto    |
| `mermaid.puppeteer_config=PATH` | Puppeteer config passed to mermaid-cli as `-p`.                                                                | none    |

A template can set a base config with the `mermaid` key in `template.yaml` or by overriding `Template.mermaid_config()` (see [TEMPLATING.md](TEMPLATING.md)). `mermaid.config` is merged over it, then `mermaid.theme`.

```bash
ope export ./Notes -O mermaid.config=mermaid.json
```

```json
{ "theme": "base", "themeVariables": { "primaryColor": "#e8eef5", "pie1": "#2c5282" } }
```

Notes:

- WeasyPrint clips text that is centered inside a semi-transparent group. Gantt axis labels are drawn that way, so the exporter adds `.grid .tick { opacity: 1 }` to the `themeCSS` of SVG diagrams.
- Flowchart edge labels use the theme's `edgeLabelBackground`. With the `base` theme it is derived from the theme colors and can look purple. Set `themeVariables.edgeLabelBackground` to change it.
- When running as root (for example in a CI container), Chromium needs `--no-sandbox`. The exporter passes it automatically in that case.

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
