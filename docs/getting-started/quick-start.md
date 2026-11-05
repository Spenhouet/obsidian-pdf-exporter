---
title: Quick start
description: Export a vault folder to PDF, set title and version, pick a template and inspect the result.
---

# Quick start

## Export a folder

```bash
ope export ./MyVault/Handbook
```

The PDF is written to `./.export/Handbook.pdf`. The folder name is the title. Every subfolder becomes a section, see [Folder Notes](../plugins/folder-notes.md).

## Title, version and output

```bash
ope export ./MyVault/Handbook \
  --title "Team handbook" --subtitle "How we work" \
  --version 3.1.0 --date 2026-05-07 \
  --output ./out/handbook.pdf
```

The title and subtitle go into the title block and the running header. The version and date go into the footer of the `default` template. Without `--version`, a folder inside a git repository shows the short commit hash.

## Only some chapters

```bash
ope export ./MyVault/Handbook --include "Chapter A" --include "Chapter B"
ope export ./MyVault/Handbook --exclude "Drafts" --no-toc
```

`--include` and `--exclude` take names of the top-level subfolders.

## Only notes with a tag

```bash
ope export ./MyVault/Handbook --tag security
ope export ./MyVault/Handbook --tag security --tag "#onboarding" --include "Chapter A"
```

`--tag` keeps the notes that have the tag, at any depth. Tags in the `tags` property and inline tags in the text both count. The match works like the tag search of Obsidian: the leading `#` and the case do not matter, and `security` also matches the nested tag `security/backup`, but not `security-review`. With several `--tag`, a note needs one of them. Together with `--include` or `--exclude`, a note has to pass both.

A folder whose note does not have the tag stays as a heading without text when a note below it has the tag. Folders without such a note are left out. When no note has the tag, the export stops with an error and writes no PDF.

## A different look

```bash
ope list-templates
ope export ./MyVault/Handbook --template ./my-template/
```

A template is a CSS file or a folder with CSS, header and footer. See [Templates and styling](../templating/index.md).

## Settings for features

`-O key=value` passes settings to the steps, plugins and the template:

```bash
ope export ./MyVault/Handbook -O mermaid.landscape=on -O tables.landscape=off
ope export ./MyVault/Handbook --disable-plugin dataview
```

All keys are listed in the [CLI reference](../reference/cli.md#options-for-o-keyvalue).

## Tracked changes

```bash
cd MyVault
ope redline ./Handbook --from-commit v3.0.0 --to-commit HEAD
```

Inserted text is green, removed text red and struck through. See [Redline](../redline/index.md) for flags, recipes and CI.

## When something looks wrong

```bash
ope export ./MyVault/Handbook --debug
```

`--debug` keeps the build folder next to the PDF. `assembled.md` is what pandoc reads, `final.html` is what WeasyPrint lays out. See [Debugging](../templating/debugging.md).
