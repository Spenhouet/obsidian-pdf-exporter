---
title: Mermaid
description: Mermaid code blocks rendered to SVG or PNG diagrams with mermaid-cli.
---

# Mermaid

` ```mermaid ` blocks are drawn with [mermaid-cli](https://github.com/mermaid-js/mermaid-cli). ope uses `mmdc` if it is on the `PATH`, else `npx -y @mermaid-js/mermaid-cli@11.4.2` when Node.js is installed. Without either, the blocks stay code blocks and the export prints a warning. A block that fails to render also stays code.

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Markdown</p>

````markdown
--8<-- "examples/mermaid/mermaid.md"
````

</div>
<div markdown>
<p class="ope-label">PDF</p>

![A flowchart and a sequence diagram](../img/features/mermaid.png)

</div>
</div>

The default output is SVG, so text stays sharp and can be searched. Mermaid normally puts labels in HTML `<foreignObject>` elements, which WeasyPrint does not draw, so for SVG output ope always sets `htmlLabels: false`. Use PNG for a diagram type that needs HTML labels.

## Options

| Option | Effect | Default |
| ------ | ------ | ------- |
| `-O mermaid=off` | Keep Mermaid blocks as code. | on |
| `-O mermaid.format=svg\|png` | Output format. | `svg` |
| `-O mermaid.scale=N` | Pixel density of PNG output. The image keeps its natural size. | `3` |
| `-O mermaid.config=PATH` | JSON [Mermaid config](https://mermaid.js.org/config/schema-docs/config.html) (`theme`, `themeVariables`, ...). | none |
| `-O mermaid.theme=NAME` | Shortcut for `theme`: `default`, `neutral`, `dark`, `forest`, `base`. | none |
| `-O mermaid.cli=COMMAND` | Command that runs mermaid-cli. | auto |
| `-O mermaid.puppeteer_config=PATH` | Puppeteer config passed as `-p`. | none |
| `-O mermaid.trim=on\|off` | Trim the empty space around diagrams. | `on` |
| `-O mermaid.max_height=LENGTH` | Largest height, such as `10cm`. Taller diagrams are scaled down. | none |
| `-O mermaid.landscape=on\|off` | Put wide diagrams on landscape pages. | `on` |
| `-O mermaid.landscape_ratio=R` | Width to height ratio from which a diagram that has to shrink goes to landscape. | `1.4` |
| `-O mermaid.landscape_min_font=PT` | Smallest text size a diagram may shrink to on a portrait page before it goes to landscape. | `7` |

A template can set a base config with the `mermaid` key in `template.yaml` or `Template.mermaid_config()`. `mermaid.config` is merged over it, then `mermaid.theme`.

```bash
ope export ./Notes -O mermaid.config=mermaid.json
```

```json
{ "theme": "base", "themeVariables": { "primaryColor": "#e8eef5", "pie1": "#2c5282" } }
```

## Diagram size

A diagram keeps its natural size and only shrinks when it is wider than the text. `mermaid.max_height` scales down taller ones. Other sizes belong in the template's CSS: every diagram has the classes `doc-image`, `mermaid` and `mermaid-<type>`, see [CSS reference](../templating/css-reference.md#mermaid-diagrams).

Mermaid leaves empty space around some diagram types. ope trims it to a margin of 8 px. PNG images are cropped. For SVG, mermaid-cli renders a second, transparent PNG to find the visible area, and ope shrinks the `viewBox`. That takes a few seconds, `-O mermaid.trim=off` skips it.

`%%` comment lines in a block are removed before rendering.

## Wide diagrams

A diagram wider than the text shrinks, and so does its text. When that makes it hard to read, the diagram goes to its own landscape page, like a [wide table](../markdown/tables.md#wide-tables).

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Markdown</p>

````markdown
--8<-- "examples/mermaid-landscape/mermaid-landscape.md"
````

</div>
<div markdown>
<p class="ope-label">PDF</p>

![A wide flowchart on a landscape page, with its caption](../img/features/mermaid-landscape.png)

</div>
</div>

A diagram moves when it has to shrink to fit a portrait page and either its width is at least `mermaid.landscape_ratio` times its height, or its text would get smaller than `mermaid.landscape_min_font` points. It only moves when the landscape page shows it larger, so a tall diagram stays where it is. On the landscape page it is sized to fit the page height, with room for a caption.

A short paragraph right below the diagram that starts with a word and a number, such as `Figure 1: Overview`, is its caption and moves with it. The diagram gets the class `landscape`, its wrapper `wide-table-section landscape-figure`, so a template's landscape page for tables applies to diagrams too.

```bash
ope export ./Notes -O mermaid.landscape_ratio=2
ope export ./Notes -O mermaid.landscape=off
```

!!! note
    In the picture above the right edge of the last box is cut off. That comes from the trimming of empty space ([#69](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/69)); `-O mermaid.trim=off` avoids it.

## Notes

- WeasyPrint clips text centered in a semi-transparent group. Gantt axis labels are drawn that way, so ope adds `.grid .tick { opacity: 1 }` to the `themeCSS` of SVG diagrams.
- Wrapped labels in timeline diagrams carry a line offset twice. ope removes the outer one, so the text stays in its box.
- Flowchart edge labels use `edgeLabelBackground`. With the `base` theme it can look purple. Set `themeVariables.edgeLabelBackground` to change it.
- When running as root (in a CI container), Chromium needs `--no-sandbox`. ope passes it in that case.
