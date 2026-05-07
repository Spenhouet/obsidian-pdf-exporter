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


@app.command()
def version() -> None:
    """Print the installed version."""
    from obsidian_pdf_exporter import __version__

    typer.echo(f"obsidian-pdf-exporter {__version__}")


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
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Keep the intermediate build directory for inspection",
    ),
) -> None:
    """Export an Obsidian-format folder tree to a single PDF file."""
    options = _parse_options(option)
    chosen_title = title or root.name
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
    )
    _run(lambda: export_pdf(request, log=_log))


@app.command()
def redline(
    root: Path = typer.Argument(..., help="Path to the vault folder to export"),
    from_commit: str = typer.Option(
        ...,
        "--from-commit",
        help="Older git commit ref (baseline)",
    ),
    to_commit: str = typer.Option(
        "HEAD",
        "--to-commit",
        help="Newer git commit ref (default: HEAD)",
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
        help="Document title (default: folder name)",
    ),
    subtitle: str | None = typer.Option(None, "--subtitle", help="Document subtitle"),
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
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Keep the intermediate build directory for inspection",
    ),
) -> None:
    """Generate a redline (tracked-changes) PDF between two git commits."""
    if not is_git_repo(Path.cwd()):
        _console.print(
            "[red]ERROR:[/red] redline requires the vault to be in a git repository. "
            "Run `git init` and commit your vault, or use `export` instead."
        )
        raise typer.Exit(code=1)

    options = _parse_options(option)
    chosen_title = title or root.name
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
        from_commit=from_commit,
        to_commit=to_commit,
        title=chosen_title,
        subtitle=subtitle or "",
        options=options,
        disabled_plugins=set(disable_plugin),
        debug=debug,
    )
    _run(lambda: export_redline(request, log=_log))


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
    _console.print(message, highlight=False)


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
