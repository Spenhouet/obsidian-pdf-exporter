"""CLI entry point for obsidian-pdf-exporter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from obsidian_pdf_exporter.core.exporter import ExportRequest
from obsidian_pdf_exporter.core.exporter import RedlineRequest
from obsidian_pdf_exporter.core.exporter import export_pdf
from obsidian_pdf_exporter.core.exporter import export_redline
from obsidian_pdf_exporter.core.util import is_git_repo
from obsidian_pdf_exporter.core.util import safe_filename

if TYPE_CHECKING:
    from obsidian_pdf_exporter.dependencies import Diagnosis
from obsidian_pdf_exporter.plugins import available_plugins
from obsidian_pdf_exporter.templates import load_template
from obsidian_pdf_exporter.templates import resolve_template
from obsidian_pdf_exporter.templates import template_sources
from obsidian_pdf_exporter.templates import user_templates_dir

app = typer.Typer(
    name="obsidian-pdf-exporter",
    help="Export Obsidian vaults to PDF with plugin support. Runs locally or in CI.",
    no_args_is_help=True,
)

_console = Console()


def _print_version() -> None:
    from obsidian_pdf_exporter import __version__

    typer.echo(f"obsidian-pdf-exporter {__version__}")


def _version_callback(value: bool) -> None:
    if value:
        _print_version()
        raise typer.Exit


@app.callback()
def main(
    _version: bool = typer.Option(
        False,
        "--version",
        help="Print the installed version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Export Obsidian vaults to PDF with plugin support. Runs locally or in CI."""


@app.command()
def version() -> None:
    """Print the installed version."""
    _print_version()


@app.command()
def setup(
    check: bool = typer.Option(
        False,
        "--check",
        help="Diagnose only — do not install anything (exit 1 if something is missing)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
) -> None:
    """Install missing system dependencies (Pango/HarfBuzz/Fontconfig, pandoc)."""
    from obsidian_pdf_exporter.dependencies import apply_fix
    from obsidian_pdf_exporter.dependencies import diagnose

    d = diagnose()

    if d.ok:
        _console.print("[green]All system dependencies are already installed.[/green]")
        return

    _print_diagnosis(d)

    if check:
        if d.fix_command:
            _console.print(f"\n[bold]Would run:[/bold] {d.fix_command}")
        if not d.pandoc_present:
            _console.print(
                "[bold]Would download pandoc[/bold] from the upstream pandoc GitHub release."
            )
        raise typer.Exit(code=1)

    installed = [*d.missing_libs]
    if not d.pandoc_present:
        installed.append("pandoc")

    code = apply_fix(d, assume_yes=yes)
    if code == 0:
        _console.print(
            f"[green]Installed:[/green] {', '.join(installed)}.",
        )
    raise typer.Exit(code=code)


def _print_diagnosis(d: Diagnosis) -> None:
    table = Table(title=f"obsidian-pdf-exporter setup — {d.platform}")
    table.add_column("Check")
    table.add_column("Status")
    for lib in (
        "gobject-2.0",
        "pango-1.0",
        "pangoft2-1.0",
        "harfbuzz",
        "harfbuzz-subset",
        "fontconfig",
    ):
        ok = lib not in d.missing_libs
        table.add_row(lib, "[green]OK[/green]" if ok else "[red]MISSING[/red]")
    table.add_row(
        "pandoc",
        "[green]OK[/green]" if d.pandoc_present else "[red]MISSING[/red]",
    )
    _console.print(table)
    for note in d.notes:
        _console.print(f"[dim]· {note}[/dim]")


@app.command("list-templates")
def list_templates() -> None:
    """List all known PDF templates (built-in, packaged, user-config, runtime)."""
    sources = template_sources()
    user_dir = user_templates_dir()
    table = Table(title=f"Available templates  (user dir: {user_dir})")
    table.add_column("Name", style="bold")
    table.add_column("Source")
    table.add_column("Description")
    for name in sorted(sources):
        tpl = load_template(name)
        desc = getattr(tpl, "description", "") or ""
        table.add_row(name, sources[name], desc)
    _console.print(table)


@app.command("list-plugins")
def list_plugins() -> None:
    """List all installed Obsidian-plugin support modules (built-in + third-party)."""
    plugins = available_plugins()
    table = Table(title="Available Obsidian plugins")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    table.add_column("Class")
    rows = sorted(plugins.items(), key=lambda kv: (getattr(kv[1], "priority", 100), kv[0]))
    for name, cls in rows:
        desc = getattr(cls, "description", "") or ""
        table.add_row(name, desc, f"{cls.__module__}.{cls.__name__}")
    _console.print(table)


@app.command()
def export(  # noqa: PLR0913 - typer commands enumerate every CLI flag
    root: Path = typer.Argument(..., help="Path to the vault folder to export"),
    template: str = typer.Option(
        "default",
        "--template",
        "-T",
        help=(
            "Template name (see `list-templates`) or path to a custom template "
            "(.css file or directory with template.yaml)"
        ),
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output PDF path (default: ./.export/<title>.pdf)",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        "-t",
        help="Document title (default: folder name)",
    ),
    subtitle: str | None = typer.Option(None, "--subtitle", help="Document subtitle"),
    docversion: str | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Document version (e.g. 3.1.0)",
    ),
    date: str | None = typer.Option(
        None,
        "--date",
        "-d",
        help="Document date (YYYY-MM-DD, default: today)",
    ),
    include: list[str] = typer.Option(
        [],
        "--include",
        help="Only include these subfolder names",
    ),
    exclude: list[str] = typer.Option(
        [],
        "--exclude",
        help="Exclude these subfolder names",
    ),
    option: list[str] = typer.Option(
        [],
        "--option",
        "-O",
        help="Pass key=value options to plugins / template (repeatable)",
    ),
    disable_plugin: list[str] = typer.Option(
        [],
        "--disable-plugin",
        help="Skip the named Obsidian plugin (repeatable; see `list-plugins`)",
    ),
    toc: bool = typer.Option(
        True,
        "--toc/--no-toc",
        help="Include a table of contents at the start of the document",
    ),
    blame: bool = typer.Option(
        False,
        "--blame",
        help=(
            "Add a strip next to every page with the last commit that changed each block "
            "(author, date, message; details on hover)"
        ),
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Keep the intermediate build directory for inspection",
    ),
) -> None:
    """Export an Obsidian-format folder tree to a single PDF file."""
    options = _parse_options(option)
    chosen_title = default_title(title, root)
    output_path = output or _default_output(chosen_title)

    try:
        tpl = resolve_template(template)
    except (KeyError, FileNotFoundError, ValueError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e

    request = ExportRequest(
        root=root,
        output=output_path,
        template=tpl,
        title=chosen_title,
        subtitle=subtitle or "",
        version=docversion or "",
        date=date or "",
        include=list(include),
        exclude=list(exclude),
        options=options,
        disabled_plugins=set(disable_plugin),
        debug=debug,
        toc=toc,
        blame=blame,
    )
    _run(lambda: export_pdf(request, log=_log))


@app.command()
def redline(  # noqa: PLR0913 - typer commands enumerate every CLI flag
    root: Path = typer.Argument(
        ..., help="Folder or note to compare (with --from-path: the newer version on disk)"
    ),
    from_commit: str | None = typer.Option(
        None,
        "--from-commit",
        help="Older git commit ref (baseline)",
    ),
    to_commit: str | None = typer.Option(
        None,
        "--to-commit",
        help="Newer git commit ref (default: HEAD)",
    ),
    from_path: Path | None = typer.Option(
        None,
        "--from-path",
        help=(
            "Older version as a folder or note on disk (baseline), compared with ROOT on disk "
            "without git; not with --from-commit, --to-commit or --blame"
        ),
    ),
    template: str = typer.Option(
        "redline",
        "--template",
        "-T",
        help=(
            "Template name (default: redline) or path to a custom template "
            "(.css file or directory with template.yaml)"
        ),
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output PDF path (default: ./.export/<title>_redline.pdf)",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        "-t",
        help="Document title (default: folder or note name)",
    ),
    subtitle: str | None = typer.Option(None, "--subtitle", help="Document subtitle"),
    option: list[str] = typer.Option(
        [],
        "--option",
        "-O",
        help=(
            "Pass key=value options to plugins / template (repeatable), e.g. "
            "redline.style=side-by-side or redline.collapse=on"
        ),
    ),
    disable_plugin: list[str] = typer.Option(
        [],
        "--disable-plugin",
        help="Skip the named Obsidian plugin (repeatable; see `list-plugins`)",
    ),
    toc: bool = typer.Option(
        True,
        "--toc/--no-toc",
        help="Include a table of contents at the start of the document",
    ),
    blame: bool = typer.Option(
        False,
        "--blame",
        help=(
            "Add a strip next to every page with the last commit that changed each block "
            "(author, date, message; details on hover)"
        ),
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Keep the intermediate build directory for inspection",
    ),
) -> None:
    """Generate a redline (tracked-changes) PDF between two versions.

    Compare two git commits of ROOT with --from-commit (and --to-commit), or two
    folders or two notes on disk with --from-path OLD (ROOT is the newer one).
    Choose the look with -O redline.style=blackline (default) or
    -O redline.style=side-by-side, and show only the changes with
    -O redline.collapse=on.
    """
    _check_redline_sources(root, from_commit, to_commit, from_path, blame=blame)

    options = _parse_options(option)
    chosen_title = default_title(title, root)
    output_path = output or _default_output(chosen_title, suffix="_redline")

    try:
        tpl = resolve_template(template)
    except (KeyError, FileNotFoundError, ValueError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e

    request = RedlineRequest(
        root=root,
        output=output_path,
        template=tpl,
        from_commit=from_commit or "",
        to_commit=to_commit or "HEAD",
        from_path=from_path,
        title=chosen_title,
        subtitle=subtitle or "",
        options=options,
        disabled_plugins=set(disable_plugin),
        debug=debug,
        toc=toc,
        blame=blame,
    )
    _run(lambda: export_redline(request, log=_log))


def _check_redline_sources(
    root: Path,
    from_commit: str | None,
    to_commit: str | None,
    from_path: Path | None,
    *,
    blame: bool,
) -> None:
    """Stop with a clear message when the two versions of a redline are not given right."""
    problem = ""
    if from_path is not None and (from_commit or to_commit):
        problem = "--from-path cannot be combined with --from-commit or --to-commit."
    elif from_path is not None and blame:
        problem = (
            "--blame needs the git history of both versions and cannot be used with "
            "--from-path. Use --from-commit, or `ope export --blame` for one version."
        )
    elif from_path is not None and from_path.is_file() != root.is_file():
        problem = "--from-path and ROOT must both be folders or both be notes."
    elif from_path is None and not from_commit:
        problem = "Name the older version with --from-commit REF or --from-path PATH."
    elif from_path is None and not is_git_repo(Path.cwd()):
        problem = (
            "redline with --from-commit requires the vault to be in a git repository. "
            "Run `git init` and commit your vault, use --from-path to compare two folders "
            "or notes, or use `export` instead."
        )
    if problem:
        _console.print(f"[red]ERROR:[/red] {problem}")
        raise typer.Exit(code=1)


def default_title(title: str | None, root: Path) -> str:
    """The title of the PDF: ``title``, or the real name of the folder or note (also for ``.``)."""
    if title:
        return title
    resolved = root.resolve()
    return resolved.stem if resolved.is_file() else resolved.name


def _default_output(title: str, suffix: str = "") -> Path:
    export_dir = Path.cwd() / ".export"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir / f"{safe_filename(title)}{suffix}.pdf"


def _parse_options(raw: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            msg = f"--option must be key=value, got {item!r}"
            raise typer.BadParameter(msg)
        key, value = item.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _log(message: str) -> None:
    _console.print(message, highlight=False, markup=False)


def _run(action) -> None:  # noqa: ANN001 - any zero-arg callable
    try:
        action()
    except Exception as e:
        import traceback

        _console.print(f"[red]ERROR:[/red] {e}")
        traceback.print_exc(file=sys.stderr)
        raise typer.Exit(code=1) from e


if __name__ == "__main__":
    app()
