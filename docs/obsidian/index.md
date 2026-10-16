---
title: Obsidian
description: The Obsidian core syntax ope supports, one step per feature, and the order the steps run in.
---

# Obsidian

The second layer of an export handles the syntax Obsidian adds to Markdown, without any community plugin. Each piece of syntax is a small step in [`core/steps/`](https://github.com/Spenhouet/obsidian-pdf-exporter/tree/main/obsidian_pdf_exporter/core/steps). All steps are listed in `CORE_STEPS` in `core/steps/__init__.py`.

## Features

| Feature | Page |
| ------- | ---- |
| Folders as sections, table of contents, numbering (folder notes come from a plugin) | [Folder Notes](../plugins/folder-notes.md) |
| `[[Page]]`, `[[Page\|alias]]`, `[[#Heading]]` | [Wiki links](wiki-links.md) |
| `![[image.png\|300]]`, `![[Note]]`, `![[Note#Heading]]`, `![[Note#^id]]` | [Embeds](embeds.md) |
| `^block-id` | [Block IDs](block-ids.md) |
| `> [!note] Title` | [Callouts](callouts.md) |
| `==highlight==`, `%% comment %%` | [Highlights and comments](highlights-comments.md) |
| `#tag` | [Tags](tags.md) |
| YAML frontmatter | [Properties](properties.md) |
| `- [ ] task` | [Tasks](tasks.md) |
| A newline is a line break | [Line breaks](line-breaks.md) |
| ` ```mermaid ` | [Mermaid](mermaid.md) |
| `[^1]`, `^[note]` | [Footnotes](../markdown/footnotes.md) |
| `![[Books.base]]`, ` ```base ` | [Bases](bases.md) |

## Order of the steps

The markdown steps run on every page in this order. The order matters: an embed inside an HTML comment is not expanded, because comments are removed first, and block IDs in embedded text are removed because embeds run before them.

| Priority | Step | Why here |
| -------- | ---- | -------- |
| 10 | `frontmatter` | Plugins read the parsed frontmatter. |
| 20 | `plugins` | Community plugins see Obsidian source syntax. |
| 30 | `html_comments` | Commented-out embeds are not expanded. |
| 35 | `bases` | Before embeds, so `![[x.base]]` is rendered as a view. |
| 38 | `pdf_embeds` | Before embeds, so `![[x.pdf#page=2]]` is not read as a note and heading. |
| 40 | `embeds` | Embedded content then passes all later steps. |
| 50 | `obsidian_comments` | After embeds, so embedded comments go too. |
| 60 | `block_ids` | After embeds, so embedded markers go too. |
| 65 | `footnotes` | After embeds, so each embedded note keeps its own labels. |
| 70 | `callouts` | |
| 80 | `heading_links` | Tags `[[#Heading]]` links with the page they are written on. |
| 90 | `wiki_links` | |
| 100 | `bracket_links` | After real wiki links are resolved. |
| 110 | `image_captions` | After `![[img]]` became an image. |
| 120 | `title_heading` | |
| 130 | `heading_levels` | Sees every heading of the page. |
| 135 | `plugin_code_blocks` | Warns about plugin code blocks nobody rendered. |
| 180 | `mermaid` | Runs once on the whole document. |

After pandoc, the HTML steps run: `base_css`, `empty_table_headers`, `column_widths`, `svg_images`, `heading_links`, `tasks`, `math`, `wide_tables`, `landscape_figures`, `footnotes` and `plugins`. [Contributing](../contributing.md) explains how to add a step.

## Content that is not rendered

Some content cannot be drawn in a PDF, or is not supported yet. It stays in the document in a simple form, and the export prints a line starting with `Warning:` that names the page:

- An embed of a file type other than notes, images and PDF files, such as `![[Board.canvas]]` or a video, becomes a link (or italic text when the file is not part of the export).
- A PDF embed that cannot be found or opened (for example an encrypted PDF) becomes a link the same way.
- An image that cannot be found becomes the italic text _[Image: name]_.
- A code block of a plugin ope does not render, such as ` ```tasks `, ` ```dataviewjs `, ` ```chart ` or an Admonition block ` ```ad-note `, stays a code block.
- DataviewJS and `TASK` queries become a short note in italics.

Check the warnings of an export to find such places:

```bash
ope export ./Vault 2>&1 | grep Warning:
```
