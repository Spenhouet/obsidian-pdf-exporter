"""Tests for the redline engine cases, the two styles, collapse and the blame strip."""

from __future__ import annotations

import io
import re
import subprocess
from typing import TYPE_CHECKING

import pytest
from lxml import html as lxml_html

from obsidian_pdf_exporter.core import exporter
from obsidian_pdf_exporter.core.blame import BlameIndex
from obsidian_pdf_exporter.core.blame import Commit
from obsidian_pdf_exporter.core.blame import Line
from obsidian_pdf_exporter.core.blame import build_index
from obsidian_pdf_exporter.core.blame import match_blocks
from obsidian_pdf_exporter.core.blame import normalize
from obsidian_pdf_exporter.core.exporter import ExportRequest
from obsidian_pdf_exporter.core.exporter import RedlineRequest
from obsidian_pdf_exporter.core.exporter import export_pdf
from obsidian_pdf_exporter.core.exporter import export_redline
from obsidian_pdf_exporter.core.pdf import apply_decorations
from obsidian_pdf_exporter.core.redline import diff_markdown
from obsidian_pdf_exporter.core.redline_html import STYLES
from obsidian_pdf_exporter.core.redline_html import parse_style
from obsidian_pdf_exporter.core.redline_html import render_redline
from obsidian_pdf_exporter.main import default_title
from obsidian_pdf_exporter.templates import load_template
from obsidian_pdf_exporter.templates.base import Decorations

if TYPE_CHECKING:
    from pathlib import Path


def _git(repo: Path, *args: str, author: str = "Test Author") -> None:
    env = {
        "GIT_AUTHOR_NAME": author,
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_COMMITTER_NAME": author,
        "GIT_COMMITTER_EMAIL": "author@example.com",
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(repo),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)  # noqa: S603, S607


def _vault(tmp_path: Path, versions: list[tuple[str, str]]) -> Path:
    """A git vault whose note ``Doc/Doc.md`` goes through ``versions`` (author, text)."""
    repo = tmp_path / "vault"
    (repo / "Doc").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for n, (author, text) in enumerate(versions):
        (repo / "Doc" / "Doc.md").write_text(text, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"Version {n + 1} of the document", author=author)
    return repo


def _redline_html(repo: Path, monkeypatch: pytest.MonkeyPatch, **options: str) -> str:
    """Run ``ope redline Doc --from-commit HEAD~1`` without the PDF step; return the HTML."""
    monkeypatch.chdir(repo)
    monkeypatch.setattr(exporter, "html_to_pdf", lambda _html, out, **_kw: out.write_bytes(b"%PDF"))
    output = repo / "out" / "redline.pdf"
    output.parent.mkdir(exist_ok=True)
    export_redline(
        RedlineRequest(
            root=repo / "Doc",
            output=output,
            template=load_template("redline"),
            from_commit="HEAD~1",
            options={f"redline.{k}": v for k, v in options.items()},
            debug=True,
        ),
        log=lambda _msg: None,
    )
    return (output.parent / "_build_redline" / "redline_final.html").read_text(encoding="utf-8")


def _plain(md: str) -> str:
    return re.sub(r"::: \{\.rl-block[^}]*\}\n(.*?)\n:::", r"\1", md, flags=re.DOTALL)


# ---------------------------------------------------------------------------
# Engine regressions
# ---------------------------------------------------------------------------


def test_table_rows_and_wider_columns_keep_the_table() -> None:
    """An inserted row and a wider column keep the pipe table intact."""
    old = (
        "| Device | Owner | Review |\n| ------ | ----- | ------ |\n"
        "| Laptop | Anna  | yearly |\n| Phone  | Ben   | yearly |"
    )
    new = (
        "| Device | Owner | Review    |\n| ------ | ----- | --------- |\n"
        "| Laptop | Anna  | quarterly |\n"
        "| Phone  | Chris | yearly    |\n| Tablet | Dana  | yearly    |"
    )
    rows = _plain(diff_markdown(old, new)).split("\n")
    assert all(r.startswith("|") and r.endswith("|") for r in rows)
    assert "<del>" not in rows[1]
    assert any('rl-row-ins"></span><ins>Tablet</ins>' in r for r in rows)
    assert any("<del>yearly</del><ins>quarterly</ins>" in r for r in rows)


def test_code_block_changes_are_html_lines() -> None:
    """A changed code block becomes HTML lines, never tags inside a fence."""
    out = diff_markdown("```python\nx = 1\nprint(x)\n```", "```python\nx = 2\nprint(x)\n```")
    assert "```" not in out
    assert 'class="rl-line rl-line-del">x = <del>1</del></span>' in out
    assert 'class="rl-line rl-line-ins">x = <ins>2</ins></span>' in out


def test_dissimilar_paragraphs_are_not_word_diffed() -> None:
    """Swapped paragraphs are moves or whole blocks, not a mix of single words."""
    old = (
        "## A\n\nParagraph one about apples and oranges in the basket.\n\n## B\n\n"
        "Paragraph two about pears.\n\nParagraph three about the weather today."
    )
    new = (
        "## A\n\nParagraph three about the weather today.\n\n## B\n\n"
        "Paragraph two about pears.\n\nParagraph one about apples and oranges in the basket."
    )
    out = diff_markdown(old, new)
    assert "<del>one</del><ins>three</ins>" not in out
    assert "rl-move-from" in out
    assert "rl-move-to" in out


def test_removed_callout_stays_one_block() -> None:
    """A removed callout is one block with its title and body."""
    callout = (
        '::: {.callout .callout-note data-callout="note"}\n[**Note**]{.callout-title}\n\n'
        "Old note that goes away.\n:::"
    )
    out = diff_markdown(f"Intro.\n\n{callout}", "Intro.")
    block = re.search(
        r'::: \{\.rl-block \.rl-del data-rl-kind="callout"\}\n(.*)\n:::', out, re.DOTALL
    )
    assert block is not None
    assert "Note" in block.group(1)
    assert "Old note that goes away." in block.group(1)


def test_replaced_image_is_removed_and_inserted() -> None:
    """A replaced image is a removed and an inserted figure, size attributes intact."""
    out = diff_markdown(
        "![](chart.png){.doc-image width=300}", "![](shapes.svg){.doc-image width=300}"
    )
    assert 'rl-del data-rl-kind="image" data-rl-src="chart.png"' in out
    assert 'rl-ins data-rl-kind="image" data-rl-src="shapes.svg"' in out
    assert "<del>" not in out


def test_checked_task_keeps_its_checkbox() -> None:
    """Checking a task keeps the task marker and flags the change."""
    out = diff_markdown(
        "- [ ] Review the policy\n- [ ] Sign the form",
        "- [x] Review the policy\n- [ ] Sign the form",
    )
    assert '- [x] <span class="rl-task" data-rl-task="checked"></span>Review the policy' in out
    assert "[ ]</del>" not in out


def test_heading_level_change_is_marked() -> None:
    """A heading that changes its level is marked with both levels."""
    out = diff_markdown(
        "## Scope\n\nText A.\n\n## Duties\n\nText B.",
        "## Scope\n\nText A.\n\n### Duties\n\nText B.",
    )
    assert 'data-old-level="2" data-new-level="3"' in out
    assert ".rl-mod" in out


def test_changed_footnote_is_not_wrapped() -> None:
    """A changed footnote definition is diffed in place, without block divs."""
    out = diff_markdown("A claim.[^1]\n\n[^1]: Old source.", "A claim.[^1]\n\n[^1]: New source.")
    assert "[^1]: <del>Old</del><ins>New</ins> source." in out
    assert "::: {.rl-block" not in out


def test_title_block_shows_the_range_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The title block names the compared versions once."""
    repo = _vault(tmp_path, [("A", "Text one.\n"), ("B", "Text two.\n")])
    page = _redline_html(repo, monkeypatch)
    header = lxml_html.fromstring(page).find(".//header")
    assert header is not None
    text = header.text_content()
    assert text.count("HEAD~1") == 1
    assert "Redline:" not in text


def test_changed_paragraph_before_a_new_one_keeps_its_word_diff() -> None:
    """A changed paragraph followed by a new one is diffed in place."""
    out = diff_markdown(
        "Intro.\n\nUpdates are installed once a week.",
        "Intro.\n\nUpdates are installed once a month.\n\nA new paragraph.",
    )
    assert "Updates are installed once a <del>week.</del><ins>month.</ins>" in out
    assert '::: {.rl-block .rl-ins data-rl-kind="para"}\nA new paragraph.\n:::' in out


def test_default_title_uses_the_real_folder_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ope export .`` names the PDF after the folder."""
    folder = tmp_path / "Handbook"
    folder.mkdir()
    monkeypatch.chdir(folder)
    assert default_title(None, folder.relative_to(folder)) == "Handbook"
    assert default_title("Given", folder) == "Given"


# ---------------------------------------------------------------------------
# Styles and collapse
# ---------------------------------------------------------------------------

OLD_DOC = """## Overview

Unchanged intro paragraph.

Another unchanged paragraph.

## Terms

{terms}

## Rules

Rules stay as they are.

The last rule is checked yearly.
"""


def _terms(changed: set[int]) -> str:
    return "\n".join(
        f"- **Term {n:02d}**: The {'revised ' if n in changed else ''}meaning of term {n}."
        for n in range(1, 41)
    )


@pytest.fixture
def two_versions(tmp_path: Path) -> Path:
    """A vault with a 40-item list of which most items change, and unchanged sections."""
    old = OLD_DOC.format(terms=_terms(set()))
    new = OLD_DOC.format(terms=_terms(set(range(1, 11)))).replace(
        "checked yearly", "checked monthly"
    )
    return _vault(tmp_path, [("Alex Example", old), ("Kim Reviewer", new)])


def test_unknown_style_is_an_error() -> None:
    """Only the documented styles are accepted."""
    assert parse_style({}) == "blackline"
    assert parse_style({"redline.style": "Side-by-Side"}) == "side-by-side"
    with pytest.raises(ValueError, match="Unknown redline style"):
        parse_style({"redline.style": "balloons"})


def test_blackline_has_summary_hunks_and_toc_marks(
    two_versions: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default style adds the summary, change groups and TOC marks."""
    doc = lxml_html.fromstring(_redline_html(two_versions, monkeypatch))
    assert doc.find(".//section[@id='rl-summary']") is not None
    assert doc.xpath("//div[contains(@class,'rl-hunk')]")
    assert doc.xpath("//nav[@id='TOC']//span[contains(@class,'rl-toc-mark')]")
    assert "rl-blackline" in doc.body.get("class")


def test_side_by_side_rows_stay_aligned(
    two_versions: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every list item gets a row with the old item left and the new item right."""
    doc = lxml_html.fromstring(_redline_html(two_versions, monkeypatch, style="side-by-side"))
    rows = doc.xpath("//table[contains(@class,'rl-sbs')]//tr[.//strong[starts-with(., 'Term')]]")
    assert len(rows) == 40
    for row in rows:
        old, new = (
            row.xpath("./td[contains(@class,'rl-sbs-old')]")[0],
            row.xpath("./td[contains(@class,'rl-sbs-new')]")[0],
        )
        assert old.xpath(".//strong")[0].text == new.xpath(".//strong")[0].text
    changed = [r for r in rows if "rl-sbs-mod" in r.get("class")]
    assert len(changed) == 10
    assert "V1.0" not in doc.text_content()
    assert doc.xpath("//table[contains(@class,'rl-sbs')]//td[contains(@class,'rl-sbs-gutter')]")


def test_side_by_side_long_list_breaks_between_items(
    two_versions: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 40-item list starts on the page of its heading and flows over pages."""
    weasyprint = pytest.importorskip("weasyprint")
    pdfium = pytest.importorskip("pypdfium2")
    page = _redline_html(two_versions, monkeypatch, style="side-by-side")
    pdf = pdfium.PdfDocument(weasyprint.HTML(string=page, base_url=str(tmp_path)).write_pdf())
    texts = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    heading_page = next(i for i, t in enumerate(texts) if "Terms" in t and "Term 01" in t)
    assert "Term 05" in texts[heading_page]


def test_collapse_keeps_changes_and_heading_paths(
    two_versions: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Collapse hides unchanged blocks behind one line and keeps the anchors of headings."""
    doc = lxml_html.fromstring(_redline_html(two_versions, monkeypatch, collapse="on"))
    lines = [e.text_content() for e in doc.xpath("//*[contains(@class,'rl-ctx')]")]
    assert "\u22ef unchanged: 1 Overview (2 paragraphs) \u22ef" in lines
    assert "\u22ef 30 list items unchanged \u22ef" in lines
    assert "Unchanged intro paragraph." not in doc.text_content()
    assert "checked <del>yearly.</del><ins>monthly.</ins>" in lxml_html.tostring(
        doc, encoding="unicode"
    )
    ids = set(doc.xpath("//@id"))
    targets = {h[1:] for h in doc.xpath("//nav[@id='TOC']//a/@href")}
    assert targets <= ids


def test_side_by_side_collapse_has_no_change_bar(
    two_versions: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With collapse, side by side shows only changed rows and drops the centre bar."""
    page = _redline_html(two_versions, monkeypatch, style="side-by-side", collapse="on")
    doc = lxml_html.fromstring(page)
    assert "rl-collapse" in doc.body.get("class")
    assert (
        "body.rl-collapse tr.rl-sbs-row td.rl-sbs-gutter { background: none !important; }" in page
    )
    assert doc.xpath("//tr[contains(@class,'rl-sbs-ctx')]")
    assert not doc.xpath("//tr[contains(@class,'rl-sbs-equal')][.//p]")


# ---------------------------------------------------------------------------
# Blame
# ---------------------------------------------------------------------------


def test_normalize_drops_markup() -> None:
    """Links, Meta Bind fields, callout markers and tags do not count as words."""
    assert (
        normalize("See [[Folder/Note|the note]] and `VIEW[{x}][text]` <b>now</b>")
        == "see the note and now"
    )
    assert normalize("> [!warning] Before release") == "before release"


def test_index_matches_the_newest_commit_of_a_block() -> None:
    """A block spread over two source lines takes the newer of their commits."""
    index = BlameIndex()
    index.commits["a" * 40] = Commit("a" * 40, "Old Author", 100, "old")
    index.commits["b" * 40] = Commit("b" * 40, "New Author", 200, "new")
    index.add(Line("Doc.md", normalize("The first line of a paragraph").split(), "a" * 40))
    index.add(Line("Doc.md", normalize("continues on the second line here").split(), "b" * 40))
    hit = index.match("The first line of a paragraph continues on the second line here")
    assert hit == ("b" * 40, "Doc.md")
    assert index.match("Nothing like it at all in the sources") is None


def test_build_index_and_match_blocks(tmp_path: Path) -> None:
    """Blame reads authors, emails and full messages from git."""
    repo = _vault(
        tmp_path,
        [
            (
                "Alex Example",
                "First paragraph stays as written here.\n\nSecond paragraph, old wording.\n",
            ),
            (
                "Kim Reviewer",
                "First paragraph stays as written here.\n\nSecond paragraph, new wording.\n",
            ),
        ],
    )
    index = build_index(repo, repo / "Doc")
    body = lxml_html.fromstring(
        "<html><body><p>First paragraph stays as written here.</p>"
        "<p>Second paragraph, new wording.</p></body></html>"
    ).body
    found = match_blocks(body, index)
    authors = [index.commits[sha].author for _, sha in found if sha]
    assert authors == ["Alex Example", "Kim Reviewer"]
    commit = index.commits[found[1][1] or ""]
    assert commit.email == "author@example.com"
    assert commit.message == "Version 2 of the document"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", commit.iso_date)


def test_export_with_blame_adds_strip_and_tooltips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page keeps its size, a strip is added and every line has a tooltip button."""
    pypdf = pytest.importorskip("pypdf")
    repo = _vault(
        tmp_path, [("Alex Example", "## Part\n\nA paragraph about the scope of the document.\n")]
    )
    monkeypatch.chdir(repo)
    plain, blamed = repo / "plain.pdf", repo / "blamed.pdf"
    for out, blame in ((plain, False), (blamed, True)):
        export_pdf(
            ExportRequest(
                root=repo / "Doc",
                output=out,
                template=load_template("default"),
                blame=blame,
                toc=False,
            ),
            log=lambda _msg: None,
        )
    page_plain = pypdf.PdfReader(io.BytesIO(plain.read_bytes())).pages[0]
    page_blamed = pypdf.PdfReader(io.BytesIO(blamed.read_bytes())).pages[0]
    assert float(page_blamed.mediabox.height) == pytest.approx(float(page_plain.mediabox.height))
    assert float(page_blamed.mediabox.width) > float(page_plain.mediabox.width) + 150
    text = page_blamed.extract_text()
    assert "Alex Example" in text
    tips = [a.get_object().get("/TU", "") for a in page_blamed.get("/Annots", [])]
    assert any(
        "Alex Example <author@example.com>" in t and "Version 1 of the document" in t for t in tips
    )


HEADER = '<div id="tpl-header"><img src="logo.png"> Example Inc.</div>'


@pytest.mark.parametrize("style", STYLES)
def test_template_header_is_kept_in_redline_styles(style: str) -> None:
    html = (
        "<html><head><title>T</title></head><body>"
        '<p>Old <del class="rl-del">text</del><ins class="rl-ins">words</ins>.</p>'
        "</body></html>"
    )
    redlined = render_redline(html, {"redline.style": style})
    assert "<body>" not in redlined
    decorated = apply_decorations(redlined, Decorations(running_html=HEADER))
    body = lxml_html.fromstring(decorated).body
    assert body.get("class") is not None
    assert "rl-doc" in body.get("class")
    assert body[0].get("id") == "tpl-header"


def test_missing_body_tag_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        out = apply_decorations("<p>No body</p>", Decorations(running_html=HEADER))
    assert out == "<p>No body</p>"
    assert "No <body> tag" in caplog.text
