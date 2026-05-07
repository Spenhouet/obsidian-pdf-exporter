# Installation

## 1. Install the CLI

**macOS / Linux**

```bash
curl -LsSf uvx.sh/obsidian-pdf-exporter/install.sh | sh && obsidian-pdf-exporter setup --yes
```

**Windows**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://uvx.sh/obsidian-pdf-exporter/install.ps1 | iex; obsidian-pdf-exporter setup --yes"
```

A specific version:

```bash
curl -LsSf uvx.sh/obsidian-pdf-exporter/0.0.1/install.sh | sh && obsidian-pdf-exporter setup --yes
```

The first part (`uvx.sh/…/install.sh`) installs the Python CLI via `uv tool install`. The chained `setup --yes` then installs the native runtime dependencies through your OS package manager. Split the two commands if you'd rather review the install plan first.

The shorter alias `ope` is identical to `obsidian-pdf-exporter`.

## 2. System dependencies

Two native dependencies sit outside the Python wheel:

- **[WeasyPrint](https://weasyprint.org/)** runtime libs — Pango, GLib, HarfBuzz (incl. `harfbuzz-subset`), and Fontconfig. Cairo is _not_ required (WeasyPrint ≥ 53 generates PDF directly through pydyf). The exact set of libs and the per-distro install commands follow [WeasyPrint's official first-steps guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).
- **[Pandoc](https://pandoc.org)** — fetched from the upstream [Pandoc GitHub releases](https://github.com/jgm/pandoc/releases) by `pypandoc` on demand.

The `setup` command handles both:

```bash
obsidian-pdf-exporter setup           # install what is missing (asks for confirmation)
obsidian-pdf-exporter setup --yes     # ditto, no prompt — for CI
obsidian-pdf-exporter setup --check   # diagnose only, exit 1 if something is missing
```

`setup` only ever invokes your platform's own package manager (or `pypandoc.download_pandoc()` for pandoc); it never downloads or hosts binaries itself.

| OS              | What `setup` runs (when libs are missing)                                                           | Notes                                                                                                      |
| --------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Debian / Ubuntu | `sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 …`      | Auto-detects `apt`. Same package list WeasyPrint's docs use.                                               |
| Fedora          | `sudo dnf install -y pango`                                                                         | `pango` pulls GLib, HarfBuzz, Fontconfig transitively.                                                     |
| Arch            | `sudo pacman -S --needed --noconfirm pango`                                                         | Same as Fedora — single package covers the stack.                                                          |
| openSUSE        | `sudo zypper install -y pango`                                                                      | Same as Fedora.                                                                                            |
| Alpine          | `sudo apk add pango fontconfig`                                                                     | Per WeasyPrint Alpine docs.                                                                                |
| macOS           | `brew install pango`                                                                                | Requires [Homebrew](https://brew.sh). If `brew` is missing, `setup` prints the install URL and exits 1.    |
| Windows         | `winget install --id tschoonj.GTKForWindows --accept-source-agreements --accept-package-agreements` | Installs the upstream GTK3 runtime via winget. Or install [Inkscape](https://inkscape.org/) (bundles GTK). |

Pandoc, separately: if missing, `setup` calls `pypandoc.download_pandoc()` which pulls the binary straight from the official Pandoc GitHub release — same source on every OS, no package-manager involvement.

If your environment is unusual and WeasyPrint cannot find the libs after install, set `OBSIDIAN_PDF_GTK_PATH` to an `os.pathsep`-separated list of directories containing the GTK DLLs/dylibs.
