<p align="center">
  <a href="https://spenhouet.com/obsidian-pdf-exporter/"><img src="https://raw.githubusercontent.com/Spenhouet/obsidian-pdf-exporter/9cd947d57a49e7d5eb6d4ee519bc4fa9a764a95e/logo.png" alt="obsidian-pdf-exporter"></a>
</p>
<p align="center">
  <em>Export Obsidian vaults to PDF with plugin support, and make redline PDFs of the changes between two git commits. Runs locally or in CI.</em>
</p>
<p align="center">
  <a href="https://github.com/Spenhouet/obsidian-pdf-exporter/actions/workflows/ci.yml"><img src="https://github.com/Spenhouet/obsidian-pdf-exporter/actions/workflows/ci.yml/badge.svg" alt="Test, Lint and Build"></a>
  <a href="https://github.com/Spenhouet/obsidian-pdf-exporter/actions/workflows/release.yml"><img src="https://github.com/Spenhouet/obsidian-pdf-exporter/actions/workflows/release.yml/badge.svg" alt="Build and publish to PyPI"></a>
  <a href="https://pypi.org/project/obsidian-pdf-exporter" target="_blank">
    <img src="https://img.shields.io/pypi/v/obsidian-pdf-exporter?color=%2334D058&label=PyPI%20package" alt="Package version">
   </a>
  <a href="https://spenhouet.com/obsidian-pdf-exporter/" target="_blank">
    <img src="https://img.shields.io/badge/docs-online-blue" alt="Documentation">
   </a>
</p>

**Documentation: https://spenhouet.com/obsidian-pdf-exporter/**

`ope` turns a folder of an Obsidian vault into one PDF. Every folder becomes a numbered section, and the Obsidian syntax in the notes is rendered: wiki links, embeds of notes, headings, blocks and images, callouts, highlights, tasks, footnotes, math, Mermaid and Bases. Community plugin syntax from Dataview, Meta Bind, Folder Notes, Block Link Plus, Excalidraw, draw.io and pandoc citations is rendered too. It also makes redline PDFs between two git commits, and templates control the look with CSS. It runs on the command line, without Obsidian, so it works in CI.

Each feature page of the docs shows the Markdown next to the rendered PDF.

## Redline: see every change in the PDF

`ope redline` turns two git commits of a folder into a tracked-changes PDF: inserted text underlined in blue, removed text struck through in red, moved text in purple and a change bar in the margin, in the layout of the real document. A change summary lists every changed section. The side-by-side style shows the old and the new document in two aligned columns, `-O redline.collapse=on` shows only the changes, and `--blame` adds the author, date and commit message of every changed block next to the page. It is made for reviews, approvals, audits and release notes of documents kept in git.

```bash
ope redline ./Policy --from-commit v1.0.0 --to-commit v1.1.0
```

<p align="center">
  <a href="https://spenhouet.com/obsidian-pdf-exporter/redline/"><img src="https://raw.githubusercontent.com/Spenhouet/obsidian-pdf-exporter/c8ea25fdd403f990cfbdba2d54ac5800adac597d/docs/img/redline/redline-three-up.png" alt="The same policy before and after a change, and the redline PDF with inserted, removed and changed text"></a>
</p>

Tags, branches, commit hashes and `HEAD~n` work as versions, and the docs have GitHub Actions workflows that attach a redline to every pull request or release. See [Redline](https://spenhouet.com/obsidian-pdf-exporter/redline/).

## Install

**macOS / Linux**

```bash
curl -LsSf uvx.sh/obsidian-pdf-exporter/install.sh | sh && ope setup --yes
```

**Windows**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://uvx.sh/obsidian-pdf-exporter/install.ps1 | iex; ope setup --yes"
```

`ope setup` installs the native libraries WeasyPrint needs and pandoc. See [Installation](https://spenhouet.com/obsidian-pdf-exporter/getting-started/installation/) for every OS, uv, pip and CI.

## Quick start

```bash
ope export ./MyVault/Handbook --title "Team handbook" --version 1.2.0
ope redline ./MyVault/Handbook --from-commit v1.1.0 --to-commit HEAD
ope export ./MyVault/Handbook --template ./my-template/
ope --help
```

## Documentation

| Topic | Link |
| ----- | ---- |
| Install on every OS, quick start | [Getting started](https://spenhouet.com/obsidian-pdf-exporter/getting-started/installation/) |
| Every command, flag, `-O` option, env var and exit code | [CLI reference](https://spenhouet.com/obsidian-pdf-exporter/reference/cli/) |
| Markdown: tables, code, footnotes, math | [Markdown](https://spenhouet.com/obsidian-pdf-exporter/markdown/) |
| Obsidian syntax: wiki links, embeds, callouts, Mermaid | [Obsidian](https://spenhouet.com/obsidian-pdf-exporter/obsidian/) |
| Dataview, Meta Bind, Excalidraw, draw.io, writing a plugin | [Plugins](https://spenhouet.com/obsidian-pdf-exporter/plugins/) |
| Tracked-changes PDFs: usage, comparing versions, CI, what changes look like | [Redline](https://spenhouet.com/obsidian-pdf-exporter/redline/) |
| Templates, header and footer, CSS classes, recipes | [Templates and styling](https://spenhouet.com/obsidian-pdf-exporter/templating/) |
| Claude Code plugin, skill, llms.txt | [Use with AI agents](https://spenhouet.com/obsidian-pdf-exporter/agents/) |
| Development setup, architecture, tests | [Contributing](CONTRIBUTING.md) |

## Use with AI agents

The repository is a Claude Code plugin marketplace with a skill for `ope`:

```text
/plugin install obsidian-pdf-exporter --marketplace Spenhouet/obsidian-pdf-exporter
```

On older Claude Code versions, run `/plugin marketplace add Spenhouet/obsidian-pdf-exporter` and then `/plugin install obsidian-pdf-exporter@obsidian-pdf-exporter`. Other agents can read [llms.txt](https://spenhouet.com/obsidian-pdf-exporter/llms.txt).

## License

[MIT](LICENSE)
