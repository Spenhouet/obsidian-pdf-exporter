---
name: obsidian-pdf-exporter
description: Export Obsidian vaults, folders and notes to PDF with the ope (obsidian-pdf-exporter) CLI, and make redline (tracked-changes) PDFs that show what changed in a vault folder between two git commits, tags or branches, or between two folders or notes on disk. Handles wiki links, embeds, callouts, Mermaid, math, footnotes, Bases, Dataview, Meta Bind, Excalidraw, draw.io and pandoc citations, wide tables on landscape pages, and custom PDF templates with header, footer, letterhead or logo. Installs ope if it is missing. Use when asked to export Obsidian notes or a Markdown vault to PDF, make a PDF handbook or manual from notes, create a redline, diff or tracked-changes PDF of documentation (for a review, approval, audit, release or pull request), style or brand an exported PDF, change its header or footer, or debug how a note renders in the PDF.
---

# obsidian-pdf-exporter (`ope`)

`ope` turns a folder of an Obsidian vault into one PDF, and `ope redline` turns two git commits of that folder into a tracked-changes PDF. It runs on the command line without Obsidian. `ope` and `obsidian-pdf-exporter` are the same command. Full docs: https://spenhouet.com/obsidian-pdf-exporter/ (for a page index, read https://spenhouet.com/obsidian-pdf-exporter/llms.txt).

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

`ope setup` uses the platform package manager (apt, dnf, pacman, zypper, apk, brew, winget) and may need sudo. If it cannot install, report the command it printed to the user instead of working around it. Mermaid diagrams need nothing else: they are drawn by Pele inside ope.

## Export

```bash
ope export ./Vault/Handbook                       # -> ./.export/Handbook.pdf
ope export ./Vault/Handbook -o out/handbook.pdf \
  --title "Team handbook" --subtitle "How we work" --version 1.2.0 --date 2026-04-01
ope export ./Vault/Handbook --include "Part A" --exclude Drafts --no-toc
ope export ./Vault/Handbook -O tables.landscape=off -O mermaid.landscape=off
ope export ./Vault/Handbook --disable-plugin dataview
```

- `ROOT` is a folder. Every subfolder becomes a numbered section, and `Folder/Folder.md` (the folder note) is its text. `ROOT/ROOT.md` is the first text. To export a single note, put it in its own folder named like the note.
- Links and embeds are looked up in the whole vault (the folder with `.obsidian`, else the git root).
- Without `--version`, a folder in a git repository shows the short commit hash as version.
- Other `-O` keys: `line_breaks=hard|soft`, `links.outside=text|italic`, `footnotes=page|end`, `mermaid=off`, `mermaid.config=mermaid.json`, `mermaid.landscape=off`, `excalidraw.auto_export=off`, `citations.bibliography=refs.bib`, `citations.csl=style.csl`, `tables.landscape_min_cols=N`. List: https://spenhouet.com/obsidian-pdf-exporter/reference/cli/
- Exit codes: `0` ok, `1` export failed, `2` bad arguments (for example an unknown template).

Lines starting with `Warning:` name content that could not be rendered: an embed that was not found, a canvas embed or a PDF that cannot be opened (kept as a link), a plugin code block nobody renders (`tasks`, `ad-note`, ...), a Dataview query or DataviewJS script that failed. `Warning: Link to note outside the PDF: "Note" ...` and `Warning: Link to heading outside the PDF: "#heading" ...` name a link whose target is not part of the PDF; nothing is missing, the link text is plain text in the PDF (`-O links.outside=italic` shows it in italics). Report them to the user. All messages: https://spenhouet.com/obsidian-pdf-exporter/reference/warnings/

## Redline (tracked changes)

A headline feature: a PDF of the folder in its newer version with a change summary, inserted text blue and underlined, removed text red and struck through, moved text purple, and a change bar in the margin. `-O redline.style=side-by-side` shows the old and the new document in two aligned columns, `-O redline.collapse=on` shows only the changes, `--blame` (also on `ope export`) adds author, date and commit message of each block next to the page. Docs: https://spenhouet.com/obsidian-pdf-exporter/redline/

```bash
cd Vault   # must run inside the git repository that holds ROOT
ope redline ./Handbook --from-commit v1.0.0 --to-commit v1.1.0      # release vs previous release
ope redline ./Handbook --from-commit "$(git merge-base main HEAD)"  # branch / pull request vs main
ope redline ./Handbook --from-commit HEAD~3 -o out/handbook_redline.pdf --subtitle "Review draft"
ope redline ./Handbook --from-path ./archive/Handbook                # two folders on disk, no git
```

- Refs are anything git resolves: tags, branches, SHAs, `HEAD~n` (not `a..b` ranges). `--to-commit` defaults to `HEAD`. Both sides come from git, so uncommitted changes are not included: commit first. `ROOT` may also be a single note.
- Without git, compare two folders or two notes on disk with `ope redline NEW --from-path OLD` (not with `--from-commit`, `--to-commit` or `--blame`; each side resolves embeds in its own vault, the closest folder above it with `.obsidian`): https://spenhouet.com/obsidian-pdf-exporter/redline/compare/#without-git
- Default output `./.export/<title>_redline.pdf`; the subtitle is `Changes from <from> to <to>`, the footer label has the short hashes. Same `-T`, `-O`, `--title`, `--toc/--no-toc`, `--disable-plugin`, `--blame`, `--debug` as `export` (no `--version`, `--date`, `--include`).
- For a pull request compare against the merge base, not the tip of `main`. In CI, check out with full history (`fetch-depth: 0`). Workflows for pull requests and releases: https://spenhouet.com/obsidian-pdf-exporter/redline/usage/#in-ci
- Embeds, Dataview and Meta Bind run before the comparison, so changes appear as they appear in the PDF. Properties that the text does not show are not compared. Images, SVG, PDF embeds and drawings are compared by file content, so a replaced file with the same name is marked as replaced.
- Not shown: uncommitted changes, properties that the text does not show, changes inside a diagram (the old and new drawing are shown). Limits: https://spenhouet.com/obsidian-pdf-exporter/redline/limitations/
- `--debug` keeps `redline_assembled.md` (the diffed Markdown) and `redline_final.html` next to the PDF. Styling (`ins`, `del`, `div.rl-block`, `--rl-ins`, `--rl-del` ...): https://spenhouet.com/obsidian-pdf-exporter/redline/styling/

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

- Interactive features have no PDF form: callouts are always open, Meta Bind inputs and buttons are removed, Dataview tasks cannot be checked and `CALENDAR` is a static month grid.
- Dataview runs like in Obsidian: all of DQL, inline queries, inline fields and DataviewJS (embedded V8, no network, 10 s per block, `-O dataview.js-timeout=N`). Settings come from `.obsidian/plugins/dataview/data.json`; `-O dataview.<setting>=value` overrides one, `-O dataview.now=2026-04-01` fixes `date(today)`.
- Canvas and video embeds are not rendered; they become links. PDF embeds are drawn as page images (`-O pdf_embeds.max_pages=N`, `-O pdf_embeds=link`).
- A bare URL is not turned into a link; use `<https://...>`.
