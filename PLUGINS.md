# Working with plugins

Plugin support modules handle syntax and files that come from community Obsidian plugins or other tools, not from Obsidian itself. Core Obsidian syntax (wiki links, embeds, callouts, ...) is handled by the core steps, see [CONTRIBUTING.md](CONTRIBUTING.md#architecture).

## Built-in modules

| Name           | Obsidian plugin                                                                                       | What it does                                                                                                                                                                                          |
| -------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `folder_notes` | [LostPaul/obsidian-folder-notes](https://github.com/LostPaul/obsidian-folder-notes)                   | Maps the `Folder/Folder.md` convention onto the folder during tree building, so a folder note becomes its section's body.                                                                             |
| `dataview`     | [blacksmithgu/obsidian-dataview](https://github.com/blacksmithgu/obsidian-dataview)                   | Renders DQL queries (`​```dataview` blocks, `=this.field` inline) as static markdown tables/lists at export time. Skipped when not running inside a git repo (because it needs vault-wide indexing). |
| `meta_bind`    | [mProjectsCode/obsidian-meta-bind-plugin](https://github.com/mProjectsCode/obsidian-meta-bind-plugin) | Resolves `VIEW[…]` widgets against the page's frontmatter (`{key}` substitution, `+` concatenation, `date(YYYY-MM-DD)` / `datetime(…)` formatting). Strips `INPUT[…]` and `BUTTON[…]`.                |
| `block_link_plus` | [Jasper-1024/block-link-plus](https://github.com/Jasper-1024/block-link-plus)                      | Resolves `![[Note#^id-id]]` range embeds, from the block marked `^id` (or a `%% %% ^id` placeholder) to the block or line marked `^id-id`. Without it, `^id-id` is looked up as a plain block ID.        |
| `drawio`       | [draw.io / diagrams.net](https://www.drawio.com/)                                                     | Turns the HTML labels of draw.io SVG exports into SVG text, since WeasyPrint does not draw `<foreignObject>`. Removes the "Text is not SVG - cannot display" note.                                    |

`obsidian-pdf-exporter list-plugins` shows the same table at runtime, including any third-party modules you have installed.

## Disabling a plugin

```bash
obsidian-pdf-exporter export ./vault --disable-plugin dataview
```

`--disable-plugin` is repeatable.

## Passing options to plugins

```bash
obsidian-pdf-exporter export ./vault -O dataview.limit=200 -O brand=acme
```

`-O key=value` flags reach every plugin hook via `context.options`, and the template via `ExportContext.options`. Naming convention for plugin-scoped options: `<plugin>.<key>`.

## Installing third-party plugin support

Anyone can publish a Python package that registers an `ObsidianPlugin` subclass under the `obsidian_pdf_exporter.obsidian_plugins` entry-point group. After `pip install <pkg>`, the plugin is available without any change to this project.

To author one, see [CONTRIBUTING.md](CONTRIBUTING.md#adding-support-for-an-obsidian-plugin).
