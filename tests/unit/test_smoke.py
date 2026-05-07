"""Smoke tests for obsidian-pdf-exporter."""

from typer.testing import CliRunner

from obsidian_pdf_exporter import __version__
from obsidian_pdf_exporter.main import app


def test_package_imports() -> None:
    """Package imports and exposes a version string."""
    assert isinstance(__version__, str)


def test_cli_help() -> None:
    """CLI --help exits 0."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
