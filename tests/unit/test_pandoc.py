"""Unit tests for the pandoc invocation helper."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from obsidian_pdf_exporter import main
from obsidian_pdf_exporter.core import pandoc


@pytest.fixture
def pandoc_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture the pandoc argv instead of running pandoc."""
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        calls.append(argv)
        Path(argv[argv.index("-o") + 1]).write_text("<html></html>", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("pypandoc.get_pandoc_path", lambda: "pandoc")
    monkeypatch.setattr(pandoc.subprocess, "run", fake_run)
    return calls


def test_render_html_includes_toc_by_default(tmp_path: Path, pandoc_argv: list[list[str]]) -> None:
    pandoc.render_html("# A", "x.css", "T", tmp_path)
    assert "--toc" in pandoc_argv[0]


def test_render_html_without_toc(tmp_path: Path, pandoc_argv: list[list[str]]) -> None:
    pandoc.render_html("# A", "x.css", "T", tmp_path, toc=False)
    assert not any(arg.startswith("--toc") for arg in pandoc_argv[0])


@pytest.mark.parametrize(("flag", "expected"), [([], True), (["--no-toc"], False)])
def test_export_cli_toc_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: list[str], expected: bool
) -> None:
    requests = []
    monkeypatch.setattr(main, "export_pdf", lambda request, **_: requests.append(request))
    result = CliRunner().invoke(
        main.app, ["export", str(tmp_path), "-o", str(tmp_path / "out.pdf"), *flag]
    )
    assert result.exit_code == 0, result.output
    assert requests[0].toc is expected
