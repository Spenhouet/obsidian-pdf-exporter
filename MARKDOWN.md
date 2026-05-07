# Markdown features

Anything pandoc's GFM dialect understands works as-is. Obsidian-specific features are handled too:

| Feature                                      | What happens                                                                                                                                                                                                    |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[[Page]]`, `[[Page#section\|alias]]`        | Resolved to an in-document anchor if the page exists in the tree, otherwise rendered as italic text.                                                                                                            |
| `![[image.png]]`, `![[image.png\|alt text]]` | Resolved against the vault index by filename. When several files share a name, the one with the deepest common ancestor with the referencing page wins. SVGs are inlined.                                       |
| `> [!note] Title …` callouts                 | Converted to fenced divs with a class per type (`note`, `tip`, `warning`, `danger`, `info`, `important`, `example`, `abstract`, `todo`, `success`/`check`/`done`, `question`/`help`, `failure`/`bug`, `quote`). |
| Inline `> [!note] text` (single line)        | Converted to an inline `<span class="callout …">`.                                                                                                                                                              |
| YAML frontmatter                             | Parsed (used by Meta Bind) and stripped before rendering.                                                                                                                                                       |
| HTML comments `<!-- … -->`                   | Stripped.                                                                                                                                                                                                       |
| Wide tables                                  | Auto-detected; rendered on landscape pages.                                                                                                                                                                     |
| Image followed by a single italic line       | The italic line is promoted to the image's caption.                                                                                                                                                             |

## Vault-index resolution rules

The whole vault is indexed once at the start of an export. Folders that contain no markdown (typical attachment folders, regardless of name) are pruned from the page tree automatically. `.git`, `.obsidian`, `.vscode` and any dotfile folder are always skipped.

For embedded images: when several files share the same filename, the index picks the one with the deepest common ancestor with the referencing page. This means a `Chapter A/img/logo.png` is preferred over `images/logo.png` for any page inside `Chapter A/`.
