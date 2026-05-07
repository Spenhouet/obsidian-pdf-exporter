<p align="center">
  <a href="https://github.com/Spenhouet/obsidian-pdf-exporter"><img src="https://raw.githubusercontent.com/Spenhouet/obsidian-pdf-exporter/9cd947d57a49e7d5eb6d4ee519bc4fa9a764a95e/logo.png" alt="obsidian-pdf-exporter"></a>
</p>
<p align="center">
  <em>Export Obsidian vaults to PDF with plugin support. Runs locally or in CI.</em>
</p>
<p align="center">
  <a href="https://github.com/Spenhouet/obsidian-pdf-exporter/actions/workflows/ci.yml"><img src="https://github.com/Spenhouet/obsidian-pdf-exporter/actions/workflows/ci.yml/badge.svg" alt="Test, Lint and Build"></a>
  <a href="https://github.com/Spenhouet/obsidian-pdf-exporter/actions/workflows/release.yml"><img src="https://github.com/Spenhouet/obsidian-pdf-exporter/actions/workflows/release.yml/badge.svg" alt="Build and publish to PyPI"></a>
  <a href="https://pypi.org/project/obsidian-pdf-exporter" target="_blank">
    <img src="https://img.shields.io/pypi/v/obsidian-pdf-exporter?color=%2334D058&label=PyPI%20package" alt="Package version">
   </a>
</p>

## Features

- Folder-tree → single PDF, preserving Obsidian's folder-note convention.
- Wiki links and embedded images resolved against a one-pass vault index.
- Obsidian callouts styled per type, YAML frontmatter parsed and stripped.
- Built-in support for [Folder Notes](https://github.com/LostPaul/obsidian-folder-notes), [Dataview](https://github.com/blacksmithgu/obsidian-dataview), and [Meta Bind](https://github.com/mProjectsCode/obsidian-meta-bind-plugin); third-party plugin support is pip-installable. See [PLUGINS.md](PLUGINS.md).
- **Redline** PDFs: tracked-changes diff between two git commits.
- Pluggable PDF templates (CSS + running header/footer + paged-media `@page` rules). Two ship in the box: `default` and `redline`. See [TEMPLATING.md](TEMPLATING.md).
- Wide tables auto-rotated to landscape pages.

## Install

**macOS / Linux**

```bash
curl -LsSf uvx.sh/obsidian-pdf-exporter/install.sh | sh && obsidian-pdf-exporter setup --yes
```

**Windows**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://uvx.sh/obsidian-pdf-exporter/install.ps1 | iex; obsidian-pdf-exporter setup --yes"
```

The chained `setup --yes` installs the native runtime dependencies (Pango/HarfBuzz/Fontconfig and pandoc) through your OS package manager. For per-OS commands, pinned versions, and CI usage see [INSTALLATION.md](INSTALLATION.md).

The shorter alias `ope` is identical to `obsidian-pdf-exporter`.

## Quick start

```bash
# Standard export
ope export ./MyVault/SpaceA

# Custom title, version, output path
ope export ./MyVault/SpaceA \
  --title "Quality Manual" --version 3.1.0 \
  --output ./out/quality-manual.pdf

# Redline between two commits (must run inside a git repo)
ope redline ./MyVault/SpaceA \
  --from-commit v3.0.0 --to-commit HEAD

# Discovery
ope list-templates
ope list-plugins
ope --help
```

Full flag reference: [COMMANDS.md](COMMANDS.md).

## Vault layout

The exporter walks a _space folder_ (the `ROOT` argument) and turns every subfolder into a section. A folder note named after its folder is the section's body:

```text
SpaceA/
├── SpaceA.md            ← root note (becomes the document's intro page)
├── images/              ← attachments folder name is irrelevant
│   └── logo.png
├── Chapter A/
│   ├── Chapter A.md     ← folder note for "Chapter A"
│   ├── img/             ← scoped attachments — picked over top-level on ties
│   │   └── logo.png
│   └── Section 1/
│       └── Section 1.md
└── Chapter B/
    └── Chapter B.md
```

Three roots are recognised:

1. `Space/Space.md` exists → used as the root note.
2. `Space/Space/Space.md` → the inner folder is the root, its siblings become children.
3. Neither → an anonymous root, immediate child folders are sections.

Folders without markdown are pruned automatically. `.git`, `.obsidian`, `.vscode` and other dotfile folders are skipped.

## Documentation

| Topic                                                       | Where                              |
| ----------------------------------------------------------- | ---------------------------------- |
| Installing the CLI and native deps; per-OS package commands | [INSTALLATION.md](INSTALLATION.md) |
| Every command, flag, env var, and exit code                 | [COMMANDS.md](COMMANDS.md)         |
| Obsidian-specific markdown features the exporter handles    | [MARKDOWN.md](MARKDOWN.md)         |
| Built-in plugins, options, authoring third-party plugins    | [PLUGINS.md](PLUGINS.md)           |
| Custom PDF templates (no-Python recipes + full Python spec) | [TEMPLATING.md](TEMPLATING.md)     |
| Development setup, testing, PR guidelines                   | [CONTRIBUTING.md](CONTRIBUTING.md) |

## License

[MIT](LICENSE)
