---
title: Installation
description: Install obsidian-pdf-exporter on Linux, macOS or Windows, with the native libraries WeasyPrint and pandoc need.
---

# Installation

ope is a Python package with two native dependencies: the Pango text stack that WeasyPrint uses, and pandoc. The installer below puts the CLI in place, and `ope setup` installs the native parts.

## Install the CLI

=== "Linux / macOS"

    ```bash
    curl -LsSf uvx.sh/obsidian-pdf-exporter/install.sh | sh && ope setup --yes
    ```

=== "Windows"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://uvx.sh/obsidian-pdf-exporter/install.ps1 | iex; ope setup --yes"
    ```

=== "uv"

    ```bash
    uv tool install obsidian-pdf-exporter
    ope setup --yes

    # or run it once without installing
    uvx obsidian-pdf-exporter --help
    ```

=== "pip"

    ```bash
    pip install obsidian-pdf-exporter
    ope setup --yes
    ```

The installer script installs [uv](https://docs.astral.sh/uv/) if needed and runs `uv tool install obsidian-pdf-exporter`, so the CLI lives in its own environment. A pinned version uses the version in the URL:

```bash
curl -LsSf uvx.sh/obsidian-pdf-exporter/0.5.1/install.sh | sh
```

`ope` and `obsidian-pdf-exporter` are the same command.

## Native dependencies

- [WeasyPrint](https://weasyprint.org/) needs Pango, GLib, HarfBuzz (with `harfbuzz-subset`) and Fontconfig. Cairo is not needed. The package lists follow [WeasyPrint's first steps](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).
- [Pandoc](https://pandoc.org/) converts Markdown to HTML. If it is missing, `ope setup` downloads it from the official pandoc release with `pypandoc`.

```bash
ope setup           # install what is missing, asks first
ope setup --yes     # same, without asking (for CI)
ope setup --check   # report only, exit 1 if something is missing
```

`setup` only runs the package manager of your platform:

| OS | What `setup` runs when libraries are missing | Notes |
| -- | -------------------------------------------- | ----- |
| Debian / Ubuntu | `sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 ...` | Same list as the WeasyPrint docs. |
| Fedora | `sudo dnf install -y pango` | Pulls GLib, HarfBuzz and Fontconfig. |
| Arch | `sudo pacman -S --needed --noconfirm pango` | |
| openSUSE | `sudo zypper install -y pango` | |
| Alpine | `sudo apk add pango fontconfig` | |
| macOS | `brew install pango` | Needs [Homebrew](https://brew.sh). Without it, `setup` prints the install link and exits with 1. |
| Windows | `winget install --id tschoonj.GTKForWindows --accept-source-agreements --accept-package-agreements` | The GTK3 runtime. An [Inkscape](https://inkscape.org/) install also brings GTK. |

When WeasyPrint still cannot find the libraries, set `OBSIDIAN_PDF_GTK_PATH` to the folders that hold them, separated by `os.pathsep`.

## Fonts and scripts

The PDF uses the fonts installed on the machine that runs the export. Fontconfig picks them: first the fonts the template names (`default` asks for Arial or Helvetica, then any sans-serif font, and Courier New or any monospace font for code), then, for each character that font has no glyph for, another installed font that has one. Text, tables and [Mermaid](../obsidian/mermaid.md) diagrams are laid out with the fonts that draw them, so a missing template font changes the look but not the fit.

Install fonts that cover the scripts of the notes. The [Noto](https://fonts.google.com/noto) fonts cover nearly all of them:

```bash
sudo apt-get install -y fonts-noto-core fonts-noto-cjk   # Debian, Ubuntu, CI runners
```

What happens with other text:

- A character that no installed font has is drawn as an empty box, the `.notdef` glyph of the font. The layout stays the same, and the text stays in the text layer of the PDF, so it can still be searched and copied. The export prints one warning per page, with the section, the scripts and an example:

    ```text
    Warning: Page 4 ("6 Tables") has Devanagari, Thai text that no installed font can draw, for example "नमस्ते".
    ```

    In Mermaid labels such a character is drawn as `□` and the export lists these characters in a warning of its own. There they are not in the text layer.
- Math is drawn in the math font of ziamath, which has Latin and Greek letters. A formula with other characters, such as Chinese in `\text{}`, stays as TeX source and the export prints a warning.
- Paragraphs, headings, list items and table cells that start with Hebrew or Arabic text are laid out from right to left, the way a browser does it for `dir="auto"`.
- Chinese and Japanese text breaks between characters, Thai text between words.
- A word too long for its line, such as a URL, breaks at the end of the line. In a table cell, words of 24 or more characters may break so that the table fits the page.
- Arabic or Hindi text copied out of the PDF can come out with wrong letters or in the wrong order. The printed text is right; the text layer of the PDF does not keep the letter order of shaped scripts.

## Optional tools

| Tool | Needed for |
| ---- | ---------- |
| git | [Redline](../redline/index.md), the version label from the commit hash, and the vault root for Dataview. |

## In CI

A GitHub Actions job that exports a folder and keeps the PDF:

```yaml
jobs:
  pdf:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # full history for redline and the version label
      - uses: astral-sh/setup-uv@v6
      - run: uv tool install obsidian-pdf-exporter
      - run: ope setup --yes
      - run: ope export ./Handbook --title "Team handbook" --version "${{ github.ref_name }}" -o handbook.pdf
      - uses: actions/upload-artifact@v4
        with:
          name: handbook
          path: handbook.pdf
```

[Mermaid](../obsidian/mermaid.md) diagrams are drawn inside ope, so the runner needs no Node.js or browser.

## Check the install

```bash
ope --version
ope setup --check
ope list-templates
ope list-plugins
```
