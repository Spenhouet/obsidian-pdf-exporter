---
name: obsidian-pdf-exporter
description: Export Obsidian vaults, folders and notes to PDF with the ope (obsidian-pdf-exporter) CLI. Handles wiki links, embeds, callouts, Mermaid, math, footnotes, Bases, Dataview, Meta Bind, Excalidraw, draw.io and pandoc citations, wide tables on landscape pages, redline (tracked-changes) PDFs between two git commits, and custom PDF templates with header, footer, letterhead or logo. Installs ope if it is missing. Use when asked to export Obsidian notes or a Markdown vault to PDF, make a PDF handbook or manual from notes, create a redline or diff PDF of documentation, style or brand an exported PDF, change its header or footer, or debug how a note renders in the PDF.
---

# obsidian-pdf-exporter (`ope`)

`ope` turns a folder of an Obsidian vault into one PDF. It runs on the command line without Obsidian. `ope` and `obsidian-pdf-exporter` are the same command. Full docs: https://spenhouet.com/obsidian-pdf-exporter/ (for a page index, read https://spenhouet.com/obsidian-pdf-exporter/llms.txt).

If a flag is not covered here, run `ope <command> --help`; the help is authoritative.

## Install `ope` if it is missing

```bash
if ! command -v ope >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv tool install obsidian-pdf-exporter
  elif command -v pipx >/dev/null 2>&1; then
    pipx install obsidian-pdf-exporter
  else
    curl -LsSf uvx.sh/obsidian-pdf-exporter/install.sh | sh   # installs uv, then ope
  fi
fi
command -v ope >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$PATH"
ope setup --check || ope setup --yes   # native libraries (Pango, HarfBuzz) and pandoc
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://uvx.sh/obsidian-pdf-exporter/install.ps1 | iex; ope setup --yes"
```

`ope setup` uses the platform package manager (apt, dnf, pacman, zypper, apk, brew, winget) and may need sudo. If it cannot install, report the command it printed to the user instead of working around it. Mermaid diagrams also need Node.js (`npx`) or `mmdc`; without them Mermaid blocks stay code.

## Export

```bash
ope export ./Vault/Handbook                       # -> ./.export/Handbook.pdf
ope export ./Vault/Handbook -o out/handbook.pdf \
  --title "Team handbook" --subtitle "How we work" --version 1.2.0 --date 2026-04-01
ope export ./Vault/Handbook --include "Part A" --exclude Drafts --no-toc
ope export ./Vault/Handbook -O tables.landscape=off -O mermaid.theme=neutral
ope export ./Vault/Handbook --disable-plugin dataview
```

- `ROOT` is a folder. Every subfolder becomes a numbered section, and `Folder/Folder.md` (the folder note) is its text. `ROOT/ROOT.md` is the first text. To export a single note, put it in its own folder named like the note.
- Links and embeds are looked up in the whole vault (the folder with `.obsidian`, else the git root).
- Without `--version`, a folder in a git repository shows the short commit hash as version.
- Other `-O` keys: `line_breaks=hard|soft`, `footnotes=page|end`, `mermaid=off`, `mermaid.format=svg|png`, `mermaid.landscape=off`, `excalidraw.auto_export=off`, `citations.bibliography=refs.bib`, `citations.csl=style.csl`, `tables.landscape_min_cols=N`. List: https://spenhouet.com/obsidian-pdf-exporter/reference/cli/
- Exit codes: `0` ok, `1` export failed, `2` bad arguments (for example an unknown template).

Lines starting with `Warning:` name content that could not be rendered: an embed that was not found, a canvas embed or a PDF that cannot be opened (kept as a link), a plugin code block nobody renders (`tasks`, `dataviewjs`, ...). Report them to the user.

## Redline (tracked changes)

```bash
cd Vault   # must run inside the git repository
ope redline ./Handbook --from-commit v1.0.0 --to-commit HEAD -o out/handbook_redline.pdf
```

Inserted text is green, removed text red and struck through. In CI, check out with full history (`fetch-depth: 0`).

## Templates

```bash
ope list-templates
ope export ./Vault/Handbook -T ./brand.css        # one CSS file, replaces the default CSS
ope export ./Vault/Handbook -T ./my-template/     # folder with template.yaml
ope export ./Vault/Handbook -T legal-pack         # name from ~/.config/obsidian-pdf-exporter/templates/
```

A folder or CSS-file template replaces `default` completely, including its header and footer. Start from a copy of `default.css`:

```bash
curl -sL https://raw.githubusercontent.com/Spenhouet/obsidian-pdf-exporter/main/obsidian_pdf_exporter/templates/builtin/default/default.css > my-template/main.css
```

See [references/templates.md](references/templates.md) for the folder layout, `template.yaml` keys, header and footer CSS, the classes to style and a Python template that extends `default`.

## Verify the output

Always check the PDF before reporting success:

```bash
pdfinfo out/handbook.pdf                                  # page count, page size
pdftotext -layout out/handbook.pdf - | head -80           # text, check headings and values
pdftotext out/handbook.pdf - | grep -n "VIEW\[\|\[\[\|!\[\[\|%%"   # leftover raw syntax
pdftoppm -r 60 -png -f 1 -l 2 out/handbook.pdf /tmp/page  # look at /tmp/page-1.png
```

Raw `[[...]]`, `![[...]]`, `VIEW[...]` or `%%` in the text mean something was not resolved. Look at the rendered page images to check layout, header, footer and landscape pages.

## Debug

```bash
ope export ./Vault/Handbook --debug -o out/handbook.pdf
```

Keeps `out/_build_handbook/`: `assembled.md` is what pandoc reads (after all steps and plugins), `final.html` is what WeasyPrint lays out. Wrong text: check `assembled.md`. Wrong look: check `final.html` and the CSS, or open `final.html` in a browser (it does not show page margins, headers or footers).

## What not to expect

- Interactive features have no PDF form: callouts are always open, Meta Bind inputs and buttons are removed, DataviewJS and `TASK` queries are not run.
- Dataview supports `TABLE` and `LIST` with `FROM`, `WHERE`, `SORT`, `LIMIT`.
- Canvas and video embeds are not rendered; they become links. PDF embeds are drawn as page images (`-O pdf_embeds.max_pages=N`, `-O pdf_embeds=link`).
- A bare URL is not turned into a link; use `<https://...>`.
