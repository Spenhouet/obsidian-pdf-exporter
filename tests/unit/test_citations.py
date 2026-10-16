"""Tests for the citations plugin: bibliography lookup, citation keys and citeproc."""

from __future__ import annotations

import json
import re
import shutil
from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core.pandoc import render_html
from obsidian_pdf_exporter.core.pipeline import markdown_dialect
from obsidian_pdf_exporter.core.pipeline import run_document
from obsidian_pdf_exporter.core.steps import DocumentContext
from obsidian_pdf_exporter.core.steps import core_steps
from obsidian_pdf_exporter.plugins.base import PluginContext
from obsidian_pdf_exporter.plugins.citations import CitationsPlugin
from obsidian_pdf_exporter.plugins.citations.bibliography import bibliography_keys
from obsidian_pdf_exporter.plugins.citations.bibliography import cited_keys
from obsidian_pdf_exporter.plugins.citations.bibliography import escape_unknown_bare
from obsidian_pdf_exporter.plugins.citations.bibliography import plugin_bibliography
from obsidian_pdf_exporter.plugins.citations.plugin import place_references

if TYPE_CHECKING:
    from pathlib import Path

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")

BIBTEX = """\
% Exported by Better BibTeX for Zotero
@comment{jabref-meta: databaseType:bibtex;}

@article{doe2020,
  title = {A Study of Small Things},
  author = {Doe, Jane and Roe, Richard},
  year = {2020},
  journal = {Journal of Examples},
  volume = {12},
  pages = {100--120},
  doi = {10.1234/example.2020.12},
}

@book{roe:2021,
  title = {Big Ideas},
  author = {Roe, Richard},
  publisher = {Example Press},
  address = {Springfield},
  year = {2021},
}
"""

CSL_JSON = [
    {
        "id": "smith2019",
        "type": "article-journal",
        "title": "Measuring Things",
        "author": [{"family": "Smith", "given": "Alex"}],
        "issued": {"date-parts": [[2019]]},
        "container-title": "Example Letters",
    }
]


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "refs.bib").write_text(BIBTEX, encoding="utf-8")
    (vault / "library.json").write_text(json.dumps(CSL_JSON), encoding="utf-8")
    return vault


def _ctx(vault: Path, messages: list[str], **options: str) -> DocumentContext:
    build = vault.parent / "build"
    build.mkdir(exist_ok=True)
    return DocumentContext(
        build_dir=build,
        options=options,
        root=vault,
        plugins=[CitationsPlugin()],
        log=messages.append,
    )


def _html(markdown: str, ctx: DocumentContext) -> str:
    steps = core_steps()
    markdown = run_document(markdown, ctx, steps)
    html = render_html(
        markdown, "x.css", "T", ctx.build_dir, dialect=markdown_dialect(ctx, steps), toc=False
    )
    # Keep the ids, drop the other markup, so the tests read the text.
    return re.sub(r"<(?![^>]*\bid=)[^>]+>", "", html)


# ---------------------------------------------------------------------------
# Citation syntax
# ---------------------------------------------------------------------------


def test_cited_keys() -> None:
    text = (
        "As shown [@doe2020, p. 12] and [see @roe:2021; @smith2019, ch. 2].\n"
        "@doe2020 says so. Mail me at jane@example.com. [-@roe:2021]\n"
        "A link [@x](https://example.com) and `@code` stay.\n\n```\n[@incode]\n```\n"
    )
    bracketed, bare = cited_keys(text)
    assert bracketed == ["doe2020", "roe:2021", "smith2019", "roe:2021"]
    assert bare == ["doe2020"]


def test_escape_unknown_bare_keys() -> None:
    text = "@doe2020 and @someone wrote [@someone]. `@x`"
    assert (
        escape_unknown_bare(text, {"doe2020"}) == "@doe2020 and \\@someone wrote [@someone]. `@x`"
    )


def test_bibliography_keys_bibtex_and_csl(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    assert bibliography_keys(vault / "refs.bib") == {"doe2020", "roe:2021"}
    assert bibliography_keys(vault / "library.json") == {"smith2019"}
    yaml_bib = vault / "refs.yaml"
    yaml_bib.write_text("references:\n  - id: a1\n    title: T\n", encoding="utf-8")
    assert bibliography_keys(yaml_bib) == {"a1"}


def test_plugin_settings_path_is_relative_to_the_vault(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    settings = vault / ".obsidian/plugins/obsidian-citation-plugin"
    settings.mkdir(parents=True)
    (settings / "data.json").write_text(
        json.dumps({"citationExportPath": "library.json", "citationExportFormat": "csl-json"}),
        encoding="utf-8",
    )
    assert plugin_bibliography(vault) == (vault / "library.json").resolve()


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        ("Text.\n\n::: {#refs}\n:::\n\nAfter.", "Text.\n\n::: {#refs}\n:::\n\nAfter."),
        (
            "# A\n\nText.\n\n## References\n\n# B",
            "# A\n\nText.\n\n## References\n\n::: {#refs}\n:::\n\n\n# B",
        ),
        ("Text.", "Text.\n\n# References {.unnumbered}\n\n::: {#refs}\n:::\n"),
    ],
)
def test_place_references(markdown: str, expected: str) -> None:
    assert place_references(markdown, "References") == expected


# ---------------------------------------------------------------------------
# Sources and warnings
# ---------------------------------------------------------------------------


def test_without_bibliography_citations_stay_and_warn_once(tmp_path: Path) -> None:
    vault = tmp_path / "plain"
    vault.mkdir()
    messages: list[str] = []
    ctx = _ctx(vault, messages)
    text = "One [@a]. Two [@b; @c]."
    assert run_document(text, ctx, core_steps()) == text
    assert len(messages) == 1
    assert messages[0].startswith("  Warning: 3 citation(s) such as [@a] are kept as text")
    assert list(ctx.plugins[0].pandoc_args(ctx)) == []


def test_no_citations_no_change(tmp_path: Path) -> None:
    messages: list[str] = []
    ctx = _ctx(_vault(tmp_path), messages, **{"citations.bibliography": "refs.bib"})
    assert run_document("Mail jane@example.com.", ctx, core_steps()) == "Mail jane@example.com."
    assert messages == []
    assert list(ctx.plugins[0].pandoc_args(ctx)) == []


def test_option_wins_and_missing_key_warns(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    messages: list[str] = []
    ctx = _ctx(vault, messages, **{"citations.bibliography": str(vault / "refs.bib")})
    out = run_document("See [@doe2020; @nobody].", ctx, core_steps())
    assert "::: {#refs}" in out
    assert messages == ["  Warning: citation @nobody is not in the bibliography"]
    args = list(ctx.plugins[0].pandoc_args(ctx))
    assert args[0] == "--citeproc"
    assert f"--bibliography={(vault / 'refs.bib').resolve()}" in args


def test_frontmatter_bibliography_relative_to_the_note(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    messages: list[str] = []
    ctx = _ctx(vault, messages)
    plugin = ctx.plugins[0]
    plugin.process_markdown("x", PluginContext(vault, vault, {"bibliography": "library.json"}))
    run_document("[@smith2019]", ctx, core_steps())
    assert f"--bibliography={(vault / 'library.json').resolve()}" in plugin.pandoc_args(ctx)
    assert messages == []


def test_missing_bibliography_file_warns(tmp_path: Path) -> None:
    messages: list[str] = []
    ctx = _ctx(_vault(tmp_path), messages, **{"citations.bibliography": "gone.bib"})
    run_document("[@doe2020]", ctx, core_steps())
    assert "does not exist" in messages[0]
    assert any("kept as text" in m for m in messages)


def test_off_switch(tmp_path: Path) -> None:
    messages: list[str] = []
    ctx = _ctx(_vault(tmp_path), messages, citations="off")
    assert run_document("[@a]", ctx, core_steps()) == "[@a]"
    assert messages == []


# ---------------------------------------------------------------------------
# Pandoc
# ---------------------------------------------------------------------------


@needs_pandoc
def test_citeproc_renders_citations_and_reference_list(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    messages: list[str] = []
    ctx = _ctx(
        vault,
        messages,
        **{"citations.bibliography": f"{vault / 'refs.bib'},{vault / 'library.json'}"},
    )
    html = _html(
        "# Intro\n\nAs shown [@doe2020, p. 12] and [@roe:2021; @smith2019].\n\n"
        "@doe2020 says so, @someone does not.\n",
        ctx,
    )
    assert "(Doe and Roe 2020, 12)" in html
    assert "Roe 2021; Smith 2019" in html
    assert "Doe and Roe (2020) says so" in html
    assert "@someone does not" in html
    assert 'id="refs"' in html
    assert "A Study of Small Things" in html
    assert "Measuring Things" in html
    assert re.search(r"<h1[^>]*id=\"references\"[^>]*>References", html)
    assert messages == []


@needs_pandoc
def test_citeproc_uses_the_plugin_settings(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    settings = vault / ".obsidian/plugins/obsidian-citation-plugin"
    settings.mkdir(parents=True)
    (settings / "data.json").write_text(
        json.dumps({"citationExportPath": "refs.bib", "citationExportFormat": "biblatex"}),
        encoding="utf-8",
    )
    messages: list[str] = []
    html = _html("Text [@roe:2021].\n\n## Bibliography\n\nEnd.\n", _ctx(vault, messages))
    assert "(Roe 2021)" in html
    assert html.index("Big Ideas") > html.index("Bibliography")
    assert messages == []
