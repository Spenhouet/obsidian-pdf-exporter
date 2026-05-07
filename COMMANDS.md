# Command reference

Run `obsidian-pdf-exporter --help` (or `ope --help`) for the same information from the CLI.

## `export ROOT`

Build a single PDF from a vault folder. Git is **not** required — works on any folder. If the vault is in a git repo and `--version` is omitted, the short commit hash is used as the footer label; otherwise the label is empty.

| Flag                        | Description                                                                                                              | Default                 |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------- |
| `ROOT` (positional)         | Vault folder to export.                                                                                                  | required                |
| `-T, --template NAME\|PATH` | Template name (see `list-templates`) **or** path to a custom CSS file / template directory (see [TEMPLATING.md](TEMPLATING.md)). | `default`               |
| `-o, --output PATH`         | Output PDF path.                                                                                                         | `./.export/<title>.pdf` |
| `-t, --title TEXT`          | Document title. Used in `<h1>` and the running header.                                                                   | folder name             |
| `--subtitle TEXT`           | Document subtitle.                                                                                                       | `""`                    |
| `-v, --version TEXT`        | Version label (e.g. `3.1.0`). Shown in metadata + footer.                                                                | empty                   |
| `-d, --date YYYY-MM-DD`     | Document date.                                                                                                           | today                   |
| `--include NAME`            | Only include these top-level subfolders. Repeatable.                                                                     | all                     |
| `--exclude NAME`            | Skip these top-level subfolders. Repeatable.                                                                             | none                    |
| `-O, --option key=value`    | Free-form option forwarded to plugins / template. Repeatable.                                                            | —                       |
| `--disable-plugin NAME`     | Skip a plugin (see `list-plugins`). Repeatable.                                                                          | none                    |
| `--debug`                   | Keep the intermediate build directory next to the PDF.                                                                   | off                     |

Example:

```bash
obsidian-pdf-exporter export ./MyVault/SpaceA \
  -T default \
  --title "Quality Manual" --subtitle "Process documentation" \
  --version 3.1.0 --date 2026-05-07 \
  --include "Chapter A" --include "Chapter B" \
  --disable-plugin meta_bind \
  -O brand=acme -O confidentiality=internal
```

## `redline ROOT`

Generate a tracked-changes PDF between two git commits. Must run inside the git repo that contains `ROOT`.

| Flag                        | Description                                  | Default                         |
| --------------------------- | -------------------------------------------- | ------------------------------- |
| `ROOT` (positional)         | Vault folder inside the repo.                | required                        |
| `--from-commit REF`         | Older commit-ish (baseline).                 | required                        |
| `--to-commit REF`           | Newer commit-ish.                            | `HEAD`                          |
| `-T, --template NAME\|PATH` | Template name or path (same as `export`).    | `redline`                       |
| `-o, --output PATH`         | Output PDF path.                             | `./.export/<title>_redline.pdf` |
| `-t, --title TEXT`          | Document title.                              | folder name                     |
| `--subtitle TEXT`           | Document subtitle.                           | computed from hashes            |
| `-O, --option key=value`    | Forwarded to plugins / template. Repeatable. | —                               |
| `--disable-plugin NAME`     | Skip a plugin. Repeatable.                   | none                            |
| `--debug`                   | Keep intermediates.                          | off                             |

Markup conventions in the rendered PDF:

- Word-level changes inside a single block: inline `<ins>` / `<del>` styling.
- Whole-block insertions: green `::: {.redline-ins}` block.
- Whole-block deletions: red `::: {.redline-del}` block (headings demoted to bold so deleted sections do not pollute the TOC).

## `setup`

Install missing native dependencies (Pango/HarfBuzz/Fontconfig, pandoc) via your platform's package manager. See [INSTALLATION.md](INSTALLATION.md) for the per-OS commands.

| Flag        | Description                                                                 | Default |
| ----------- | --------------------------------------------------------------------------- | ------- |
| `--check`   | Diagnose only — report what is missing and exit; do not install anything.   | off     |
| `-y, --yes` | Skip the confirmation prompt (intended for CI / chained install one-liner). | off     |

## `list-templates`

Print every known template (built-in, packaged entry-point, user-config directory, runtime-registered) with its source.

## `list-plugins`

Print every installed Obsidian-plugin support module, sorted by priority.

## `version`

Print the installed version.

## Environment variables

| Name                                  | Purpose                                                                                                   |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `OBSIDIAN_PDF_GTK_PATH`               | `os.pathsep`-separated extra directories searched for GTK/Pango libs (Windows + macOS).                   |
| `OBSIDIAN_PDF_EXPORTER_TEMPLATES_DIR` | Directory scanned for named user templates (default: `$XDG_CONFIG_HOME/obsidian-pdf-exporter/templates`). |

## Exit codes

| Code  | Meaning                                                                                |
| ----- | -------------------------------------------------------------------------------------- |
| `0`   | Success.                                                                               |
| `1`   | Runtime error during export, missing dep under `setup --check`, or install-cmd failed. |
| `2`   | Bad CLI arguments (e.g. unknown template).                                             |
| `130` | User aborted at the `setup` confirm prompt.                                            |
