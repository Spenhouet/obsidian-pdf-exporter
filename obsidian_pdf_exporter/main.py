"""CLI entry point for obsidian-pdf-exporter."""

import typer

app = typer.Typer(
    name="obsidian-pdf-exporter",
    help="Export Obsidian vaults to PDF with plugin support. Runs locally or in CI.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the installed version."""
    from obsidian_pdf_exporter import __version__

    typer.echo(f"obsidian-pdf-exporter {__version__}")


if __name__ == "__main__":
    app()
