"""Smoke tests for obsidian-pdf-exporter."""

from pathlib import Path

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


def test_redline_outside_git_repo_fails_cleanly(
    tmp_path: Path, monkeypatch: object
) -> None:
    """`redline` exits 1 with a friendly message when cwd is not a git repo."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    space = tmp_path / "Space"
    space.mkdir()
    result = CliRunner().invoke(
        app,
        ["redline", str(space), "--from-commit", "HEAD~1"],
    )
    assert result.exit_code == 1
    assert "git" in result.output.lower()
