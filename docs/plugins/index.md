---
title: Plugins
description: Support for community Obsidian plugins, how to turn it off, pass options and install third-party plugin support.
---

# Plugins

The third layer handles syntax and files from community Obsidian plugins and other tools. Each plugin support module lives in its own package under [`plugins/`](https://github.com/Spenhouet/obsidian-pdf-exporter/tree/main/obsidian_pdf_exporter/plugins), is found through an entry point and runs inside the `plugins` step of the [core steps](../obsidian/index.md#order-of-the-steps).

## Built-in plugins

| Name | Obsidian plugin | What it does | Priority |
| ---- | --------------- | ------------ | -------- |
| `folder_notes` | [Folder Notes](https://github.com/LostPaul/obsidian-folder-notes) | `Folder/Folder.md` is the text of its folder. [More](folder-notes.md) | 5 |
| `dataview` | [Dataview](https://github.com/blacksmithgu/obsidian-dataview) | Renders `TABLE` and `LIST` queries as static tables and lists. [More](dataview.md) | 10 |
| `excalidraw` | [Excalidraw](https://github.com/zsviczian/obsidian-excalidraw-plugin) | Turns drawing embeds into images. [More](excalidraw.md) | 15 |
| `meta_bind` | [Meta Bind](https://github.com/mProjectsCode/obsidian-meta-bind-plugin) | Fills `VIEW[...]` fields from the frontmatter, removes inputs and buttons. [More](meta-bind.md) | 20 |
| `block_link_plus` | [Block Link Plus](https://github.com/Jasper-1024/block-link-plus) | Resolves `![[Note#^id-id]]` range embeds. [More](block-link-plus.md) | 30 |
| `drawio` | [draw.io](https://www.drawio.com/) SVG exports | Turns HTML labels into SVG text. [More](drawio.md) | 40 |
| `citations` | [Citations](https://github.com/hans/obsidian-citation-plugin), Zotero integrations | Renders `[@key]` citations and a reference list with pandoc citeproc. [More](citations.md) | 50 |

```bash
ope list-plugins
```

shows the same list at runtime, including third-party plugins you installed.

## Turn a plugin off

```bash
ope export ./Vault --disable-plugin dataview --disable-plugin meta_bind
```

## Pass options

```bash
ope export ./Vault -O dataview.limit=200
```

`-O key=value` reaches every plugin hook as `context.options`. Plugin options use the name of the plugin as prefix: `<plugin>.<key>`.

## Third-party plugins

Any Python package can register a plugin under the `obsidian_pdf_exporter.obsidian_plugins` entry point. After `pip install` (or `uv tool install obsidian-pdf-exporter --with <package>`) it is used without any change to ope. See [Write a plugin](write-a-plugin.md).
