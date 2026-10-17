"""Smoke tests for obsidian-pdf-exporter."""

from pathlib import Path

import pytest
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


def test_cli_version_flag() -> None:
    """`--version` prints the same line as the `version` command."""
    flag = CliRunner().invoke(app, ["--version"])
    command = CliRunner().invoke(app, ["version"])
    assert flag.exit_code == 0
    assert flag.output == command.output
    assert __version__ in flag.output


def test_export_version_option_still_sets_document_version() -> None:
    """`export --version` keeps meaning the document version."""
    result = CliRunner().invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    assert "Document version" in result.output


def test_redline_outside_git_repo_fails_cleanly(tmp_path: Path, monkeypatch: object) -> None:
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


def test_log_lines_keep_square_brackets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Embeds like ![[file.pdf]] in a warning must not be read as Rich markup."""
    import io

    from rich.console import Console

    from obsidian_pdf_exporter import main

    buf = io.StringIO()
    monkeypatch.setattr(main, "_console", Console(file=buf, width=200))
    main._log("  Warning: cannot render embed ![[Manual.pdf]] [bold]x[/bold]")
    assert buf.getvalue().strip() == "Warning: cannot render embed ![[Manual.pdf]] [bold]x[/bold]"
