"""Tests for ``-O toc.depth``, the number of heading levels in the table of contents."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from lxml import html as lxml_html
from pypdf import PdfReader
from typer.testing import CliRunner

from obsidian_pdf_exporter import main
from obsidian_pdf_exporter.core import pandoc
from obsidian_pdf_exporter.core.dialect import DEFAULT_TOC_DEPTH
from obsidian_pdf_exporter.core.dialect import toc_depth
from obsidian_pdf_exporter.core.exporter import ExportRequest
from obsidian_pdf_exporter.core.exporter import export_pdf
from obsidian_pdf_exporter.core.htmltree import HtmlTree
from obsidian_pdf_exporter.core.redline_html import mark_toc
from obsidian_pdf_exporter.templates import load_template

#: A note with six heading levels.
NOTE = "".join(f"{'#' * level} Level {level}\n\nText {level}.\n\n" for level in range(1, 7))


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


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, DEFAULT_TOC_DEPTH),
        ({"toc.depth": ""}, 4),
        ({"toc.depth": "1"}, 1),
        ({"toc.depth": " 6 "}, 6),
    ],
)
def test_toc_depth_reads_the_option(options: dict[str, str], expected: int) -> None:
    assert toc_depth(options) == expected


@pytest.mark.parametrize("value", ["0", "7", "-1", "2.5", "two", "²"])
def test_toc_depth_rejects_values_outside_one_to_six(value: str) -> None:
    with pytest.raises(ValueError, match="whole number from 1 to 6"):
        toc_depth({"toc.depth": value})


def test_render_html_passes_the_depth_to_pandoc(
    tmp_path: Path, pandoc_argv: list[list[str]]
) -> None:
    pandoc.render_html("# A", "x.css", "T", tmp_path)
    pandoc.render_html("# A", "x.css", "T", tmp_path, toc_depth=2)
    assert "--toc-depth=4" in pandoc_argv[0]
    assert "--toc-depth=2" in pandoc_argv[1]


@pytest.mark.parametrize("command", ["export", "redline"])
def test_cli_stops_on_an_invalid_depth_before_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    calls = []
    monkeypatch.setattr(main, "export_pdf", lambda request, **_: calls.append(request))
    monkeypatch.setattr(main, "export_redline", lambda request, **_: calls.append(request))
    old = tmp_path / "old"
    old.mkdir()
    sources = ["--from-path", str(old)] if command == "redline" else []
    result = CliRunner().invoke(
        main.app,
        [command, str(tmp_path), *sources, "-o", str(tmp_path / "out.pdf"), "-O", "toc.depth=9"],
    )
    assert result.exit_code == 2
    assert "whole number from 1 to 6" in result.output
    assert calls == []


def _levels(nav: lxml_html.HtmlElement) -> int:
    """The number of nested list levels in the table of contents."""
    return max(len(li.xpath("ancestor::li")) + 1 for li in nav.iter("li"))


def test_export_lists_only_the_requested_levels_and_keeps_all_bookmarks(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    (vault / "Doc").mkdir(parents=True)
    (vault / "Doc" / "Doc.md").write_text(NOTE, encoding="utf-8")
    output = tmp_path / "doc.pdf"
    export_pdf(
        ExportRequest(
            root=vault,
            output=output,
            template=load_template("default"),
            options={"toc.depth": "2"},
            debug=True,
        ),
        log=lambda _msg: None,
    )
    html = (tmp_path / "_build_doc" / "final.html").read_text(encoding="utf-8")
    nav = lxml_html.fromstring(html).find(".//nav[@id='TOC']")
    assert _levels(nav) == 2

    def depth(items: list, level: int = 1) -> int:
        nested = [depth(i, level + 1) for i in items if isinstance(i, list)]
        return max([level, *nested])

    assert depth(PdfReader(output).outline) > 2


def test_redline_lists_removed_headings_only_within_the_depth() -> None:
    tree = HtmlTree(
        "<html><body>"
        "<nav id='TOC'><ul><li><a href='#a'>A</a></li></ul></nav>"
        "<h2 id='a'>A</h2>"
        "<div class='rl-heading rl-del' data-level='3'>Gone deep</div>"
        "<div class='rl-heading rl-del' data-level='2'>Gone</div>"
        "</body></html>"
    )
    mark_toc(tree, [], [], depth=2)
    nav = tree.body.find(".//nav[@id='TOC']")
    removed = [li.text_content() for li in nav.xpath(".//li[contains(@class,'rl-toc-removed')]")]
    assert removed == ["Goneremoved"]
