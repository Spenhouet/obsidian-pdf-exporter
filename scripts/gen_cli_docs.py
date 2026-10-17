#!/usr/bin/env python
"""Generate the CLI reference page from the live Typer command tree.

Every command, argument and option comes from the code, so the page cannot
drift from ``ope --help``. Extended descriptions, examples, environment
variables and exit codes are kept in this file. Run from the repository
root:

    uv run python scripts/gen_cli_docs.py           # write docs/reference/cli.md
    uv run python scripts/gen_cli_docs.py --check   # exit 1 if the page is out of date
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import typer

from obsidian_pdf_exporter.main import app

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "reference" / "cli.md"

DESCRIPTIONS: dict[str, str] = {
    "export": (
        "Builds one PDF from a vault folder. Git is not required. When the folder is in "
        "a git repository and `--version` is not set, the short commit hash is shown as "
        "the version label. See [Folder Notes](../plugins/folder-notes.md) for how the "
        "folder becomes sections."
    ),
    "redline": (
        "Builds a tracked-changes PDF between two git commits of `ROOT` (`--from-commit`, "
        "run inside the git repository that holds `ROOT`), or between two folders or notes "
        "on disk without git (`--from-path`). See [Redline](../redline/index.md) and "
        "[Comparing versions](../redline/compare.md)."
    ),
    "setup": (
        "Installs missing native dependencies (Pango, HarfBuzz, Fontconfig and pandoc) "
        "with the package manager of the platform. See "
        "[Installation](../getting-started/installation.md)."
    ),
    "list-templates": (
        "Prints every known template with its source: built-in, packaged entry point, "
        "user-config folder or registered at runtime. See "
        "[Templates](../templating/index.md)."
    ),
    "list-plugins": (
        "Prints every installed plugin support module, sorted by priority. See "
        "[Plugins](../plugins/index.md)."
    ),
    "version": "Prints the installed version. `ope --version` does the same.",
}

EXAMPLES: dict[str, str] = {
    "export": """\
ope export ./Vault/Handbook \\
  --title "Team handbook" --subtitle "How we work" \\
  --version 3.1.0 --date 2026-05-07 \\
  --include "Chapter A" --include "Chapter B" \\
  --disable-plugin meta_bind \\
  -O mermaid.theme=neutral -O tables.landscape=off""",
    "redline": "ope redline ./Vault/Handbook --from-commit v3.0.0 --to-commit HEAD",
    "setup": "ope setup --check   # report only\nope setup --yes     # install without asking",
    "list-templates": "ope list-templates",
    "list-plugins": "ope list-plugins",
    "version": "ope version",
}

OPTIONS_INDEX = """\
## Options for `-O key=value`

`-O` (`--option`) passes free-form settings to the core steps, the plugins and
the template. These keys are read by ope itself:

| Key | Values | Default | Described in |
| --- | ------ | ------- | ------------ |
| `line_breaks` | `hard`, `soft` | from `.obsidian/app.json` | [Line breaks](../obsidian/line-breaks.md) |
| `links.outside` | `text`, `italic` | `text` | [Wiki links](../obsidian/wiki-links.md#links-to-pages-outside-the-pdf) |
| `tables.landscape` | `auto`, `on`, `off` | `auto` | [Tables](../markdown/tables.md#wide-tables) |
| `tables.landscape_min_cols` | number | `6` | [Tables](../markdown/tables.md#wide-tables) |
| `mermaid` | `off` | on | [Mermaid](../obsidian/mermaid.md) |
| `mermaid.format` | `svg`, `png` | `svg` | [Mermaid](../obsidian/mermaid.md#options) |
| `mermaid.scale` | number | `3` | [Mermaid](../obsidian/mermaid.md#options) |
| `mermaid.config` | path to JSON | none | [Mermaid](../obsidian/mermaid.md#options) |
| `mermaid.theme` | Mermaid theme | none | [Mermaid](../obsidian/mermaid.md#options) |
| `mermaid.cli` | command | auto | [Mermaid](../obsidian/mermaid.md#options) |
| `mermaid.puppeteer_config` | path | none | [Mermaid](../obsidian/mermaid.md#options) |
| `mermaid.trim` | `on`, `off` | `on` | [Mermaid](../obsidian/mermaid.md#options) |
| `mermaid.max_height` | CSS length | none | [Mermaid](../obsidian/mermaid.md#options) |
| `mermaid.landscape` | `on`, `off` | `on` | [Mermaid](../obsidian/mermaid.md#wide-diagrams) |
| `mermaid.landscape_ratio` | number | `1.4` | [Mermaid](../obsidian/mermaid.md#wide-diagrams) |
| `mermaid.landscape_min_font` | points | `7` | [Mermaid](../obsidian/mermaid.md#wide-diagrams) |
| `mermaid.fit` | `on`, `off` | `on` | [Mermaid](../obsidian/mermaid.md#tall-diagrams) |
| `footnotes` | `page`, `end` | `page` | [Footnotes](../markdown/footnotes.md) |
| `pdf_embeds` | `pages`, `link` | `pages` | [Embeds](../obsidian/embeds.md#pdf) |
| `pdf_embeds.max_pages` | number | `10` | [Embeds](../obsidian/embeds.md#pdf) |
| `pdf_embeds.dpi` | number | `150` | [Embeds](../obsidian/embeds.md#pdf) |
| `citations` | `off` | on | [Citations](../plugins/citations.md#options) |
| `citations.bibliography` | paths, separated by `,` | auto | [Citations](../plugins/citations.md#bibliography) |
| `citations.csl` | path to a CSL style | Chicago author-date | [Citations](../plugins/citations.md#options) |
| `citations.title` | text | `References` | [Citations](../plugins/citations.md#options) |
| `excalidraw.auto_export` | `on`, `off` | `on` | [Excalidraw](../plugins/excalidraw.md#auto-export-files-first) |

Third-party plugins and templates can read any other key. By convention a
plugin uses `<plugin>.<key>` and a template `<template>.<key>`.
"""

TRAILER = """\
## Environment variables

| Name | Purpose |
| ---- | ------- |
| `OBSIDIAN_PDF_GTK_PATH` | Extra folders, separated by `os.pathsep`, that are searched for the GTK and Pango libraries (Windows and macOS). |
| `OBSIDIAN_PDF_EXPORTER_TEMPLATES_DIR` | Folder scanned for named user templates. Default: `$XDG_CONFIG_HOME/obsidian-pdf-exporter/templates`, or `~/.config/obsidian-pdf-exporter/templates`. |
| `XDG_CONFIG_HOME` | Moves the default user templates folder. |

## Exit codes

| Code | Meaning |
| ---- | ------- |
| `0` | Success. |
| `1` | The export failed, `setup --check` found a missing dependency, an install command failed, or `redline` ran outside a git repository. |
| `2` | Bad arguments, for example an unknown template or a malformed `-O` value. |
| `130` | Aborted at the `setup` confirmation prompt. |
"""


def render() -> str:
    root = typer.main.get_command(app)
    lines = [
        "---",
        "title: CLI reference",
        "description: Every ope command, argument, option, environment variable and exit code.",
        "---",
        "",
        "<!-- Generated by scripts/gen_cli_docs.py from the Typer app. Do not edit by hand. -->",
        "",
        "# CLI reference",
        "",
        "`ope` and `obsidian-pdf-exporter` are the same command. Run `ope --help` or "
        "`ope <command> --help` for the same information in the terminal.",
        "",
        "```text",
        "ope [--version] COMMAND [ARGS]...",
        "```",
        "",
        "| Command | Summary |",
        "| ------- | ------- |",
    ]
    commands: dict[str, Any] = root.commands  # type: ignore[attr-defined]
    for name, cmd in commands.items():
        lines.append(f"| [`{name}`](#{name}) | {first_line(cmd.help)} |")
    lines.append("")
    for name, cmd in commands.items():
        lines += render_command(name, cmd)
    lines += [OPTIONS_INDEX, TRAILER]
    return "\n".join(lines).rstrip() + "\n"


def render_command(name: str, cmd: Any) -> list[str]:  # noqa: ANN401 - click command object
    args = [p for p in cmd.params if p.param_type_name == "argument"]
    opts = [p for p in cmd.params if p.param_type_name == "option" and p.name != "help"]
    synopsis = " ".join(
        [f"ope {name}", *(a.name.upper() for a in args), "[OPTIONS]" if opts else ""]
    )
    out = [f"## `{name}`", "", first_line(cmd.help), "", "```text", synopsis.strip(), "```", ""]
    if name in DESCRIPTIONS:
        out += [DESCRIPTIONS[name], ""]
    if args:
        out += ["| Argument | Description |", "| -------- | ----------- |"]
        out += [f"| `{a.name.upper()}` | {cell(a.help or '')} (required) |" for a in args]
        out.append("")
    if opts:
        out += ["| Option | Description | Default |", "| ------ | ----------- | ------- |"]
        out += [f"| {flags(o)} | {cell(o.help or '')}{repeat(o)} | {default(o)} |" for o in opts]
        out.append("")
    if name in EXAMPLES:
        out += ["```bash", EXAMPLES[name], "```", ""]
    return out


METAVARS = {
    "template": "NAME|PATH",
    "output": "PATH",
    "title": "TEXT",
    "subtitle": "TEXT",
    "docversion": "TEXT",
    "date": "YYYY-MM-DD",
    "include": "NAME",
    "exclude": "NAME",
    "option": "KEY=VALUE",
    "disable_plugin": "NAME",
    "from_commit": "REF",
    "to_commit": "REF",
    "from_path": "PATH",
}


def first_line(text: str | None) -> str:
    return (text or "").strip().splitlines()[0] if text else ""


def flags(opt: Any) -> str:  # noqa: ANN401 - click option object
    names = sorted(opt.opts, key=len)
    if opt.secondary_opts:
        return "`" + "/".join(opt.opts + opt.secondary_opts) + "`"
    metavar = "" if opt.is_flag else " " + METAVARS.get(opt.name, opt.name.upper())
    return ", ".join(f"`{n}{metavar}`" for n in names).replace("|", "\\|")


def repeat(opt: Any) -> str:  # noqa: ANN401 - click option object
    return ". Repeatable." if opt.multiple and "repeatable" not in (opt.help or "") else ""


def default(opt: Any) -> str:  # noqa: ANN401 - click option object
    if opt.required:
        return "required"
    value = opt.default
    if opt.secondary_opts:
        return f"`{opt.opts[0] if value else opt.secondary_opts[0]}`"
    if opt.is_flag:
        return "off"
    if value in (None, [], (), ""):
        return ""
    return f"`{value}`"


def cell(text: str) -> str:
    text = " ".join(text.split()).replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("|", "\\|")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the page is out of date")
    args = parser.parse_args()
    content = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            sys.exit(f"{OUT.relative_to(REPO)} is out of date; run scripts/gen_cli_docs.py")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
