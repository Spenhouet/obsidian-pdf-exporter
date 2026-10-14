# Markdown features

Anything pandoc's GFM dialect understands works as-is. Obsidian-specific features are handled too:

| Feature                                      | What happens                                                                                                                                                                                                    |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[[Page]]`, `[[Page#section\|alias]]`        | Resolved to an in-document anchor if the page exists in the tree, otherwise rendered as italic text.                                                                                                            |
| `![[image.png]]`, `![[image.png\|alt text]]` | Resolved against the vault index by filename. When several files share a name, the one with the deepest common ancestor with the referencing page wins. SVGs are inlined.                                       |
| `![[image.png\|430]]`, `![[image.png\|430x200]]` | Width (and height) in pixels, as in Obsidian. A caption can come first: `![[image.png\|caption\|430]]`.                                                                                                     |
| `> [!note] Title …` callouts                 | Converted to fenced divs with a class per type (`note`, `tip`, `warning`, `danger`, `info`, `important`, `example`, `abstract`, `todo`, `success`/`check`/`done`, `question`/`help`, `failure`/`bug`, `quote`). |
| Inline `> [!note] text` (single line)        | Converted to an inline `<span class="callout …">`.                                                                                                                                                              |
| YAML frontmatter                             | Parsed (used by Meta Bind) and stripped before rendering.                                                                                                                                                       |
| HTML comments `<!-- … -->`                   | Stripped.                                                                                                                                                                                                       |
| Wide tables                                  | Auto-detected; rendered on landscape pages.                                                                                                                                                                     |
| Image followed by a single italic line       | The italic line is promoted to the image's caption.                                                                                                                                                             |
| ` ```mermaid ` code blocks                   | Rendered to an SVG (or PNG) diagram with mermaid-cli. See [Mermaid diagrams](#mermaid-diagrams).                                                                                                                |

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

## Vault-index resolution rules

The whole vault is indexed once at the start of an export. Folders that contain no markdown (typical attachment folders, regardless of name) are pruned from the page tree automatically. `.git`, `.obsidian`, `.vscode` and any dotfile folder are always skipped.

For embedded images: when several files share the same filename, the index picks the one with the deepest common ancestor with the referencing page. This means a `Chapter A/img/logo.png` is preferred over `images/logo.png` for any page inside `Chapter A/`.
