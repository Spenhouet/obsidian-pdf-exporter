"""Tests for note embeds (transclusion) and block ID handling."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core.assemble import process_page
from obsidian_pdf_exporter.core.callouts import convert_callouts
from obsidian_pdf_exporter.core.embeds import MAX_EMBED_DEPTH
from obsidian_pdf_exporter.core.embeds import expand_note_embeds
from obsidian_pdf_exporter.core.embeds import extract_block
from obsidian_pdf_exporter.core.embeds import extract_heading_section
from obsidian_pdf_exporter.core.embeds import rebase_headings
from obsidian_pdf_exporter.core.embeds import strip_block_ids
from obsidian_pdf_exporter.core.embeds import strip_obsidian_comments
from obsidian_pdf_exporter.core.steps import PageContext
from obsidian_pdf_exporter.core.tree import PageNode
from obsidian_pdf_exporter.core.vault_index import VaultIndex
from obsidian_pdf_exporter.plugins.block_link_plus import BlockLinkPlusPlugin

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _ctx(vault: Path, build: Path, messages: list[str] | None = None) -> PageContext:
    build.mkdir(parents=True, exist_ok=True)
    log = messages.append if messages is not None else None
    return PageContext(
        page_index={},
        build_dir=build,
        vault_root=vault,
        vault_index=VaultIndex(vault),
        log=log,
    )


# ---------------------------------------------------------------------------
# Fragment extraction
# ---------------------------------------------------------------------------


def test_extract_heading_section_stops_at_same_level() -> None:
    body = "# Top\n\n## A\n\ntext a\n\n### A.1\n\nsub\n\n## B\n\ntext b"
    assert extract_heading_section(body, ["A"]) == "## A\n\ntext a\n\n### A.1\n\nsub"


def test_extract_heading_section_nested_path() -> None:
    body = "## A\n\n### X\n\nfirst\n\n## B\n\n### X\n\nsecond"
    assert extract_heading_section(body, ["B", "X"]) == "### X\n\nsecond"


def test_extract_heading_section_ignores_code_and_missing() -> None:
    body = "```\n## A\n```\n\n## B\n\ntext"
    assert extract_heading_section(body, ["A"]) is None


def test_extract_block_paragraph_with_inline_id() -> None:
    body = "Before.\n\nFirst line\nsecond line ^para\n\nAfter."
    assert extract_block(body, "para") == "First line\nsecond line ^para"


def test_extract_block_list_item_with_children() -> None:
    body = "- one\n- two ^item\n  - nested\n- three"
    assert extract_block(body, "item") == "- two ^item\n  - nested"


def test_extract_block_standalone_id_after_table() -> None:
    body = "## Info\n| Key | Value |\n| --- | --- |\n| Name | Demo |\n^info\n\nMore."
    assert extract_block(body, "info") == "| Key | Value |\n| --- | --- |\n| Name | Demo |\n^info"


def test_extract_block_standalone_id_after_callout() -> None:
    body = "> [!note]\n> Inside.\n\n^box"
    assert extract_block(body, "box") == "> [!note]\n> Inside.\n\n^box"


_BLP = (BlockLinkPlusPlugin(),)


def test_extract_block_range() -> None:
    body = "Intro.\n\nStart here. ^r\n\n- a\n- b\n\n^r-r\n\nOutside."
    assert extract_block(body, "r-r", _BLP) == "Start here. ^r\n\n- a\n- b\n\n^r-r"


def test_extract_block_range_with_placeholder_start() -> None:
    body = "## Section\n\n%% %% ^r\n\n### Sub\n\nText.\n\n^r-r\n\n## Next"
    assert extract_block(body, "r-r", _BLP) == "%% %% ^r\n\n### Sub\n\nText.\n\n^r-r"


def test_extract_block_range_end_on_paragraph() -> None:
    body = "A. ^my-id\n\nB\nC ^my-id-my-id\n\nD"
    assert extract_block(body, "my-id-my-id", _BLP) == "A. ^my-id\n\nB\nC ^my-id-my-id"


def test_extract_block_range_needs_the_plugin() -> None:
    body = "Intro.\n\nStart here. ^r\n\n- a\n- b\n\n^r-r\n\nOutside."
    # Without Block Link Plus, ``^r-r`` is a plain block ID on its own line.
    assert extract_block(body, "r-r") == "- a\n- b\n\n^r-r"


def test_extract_block_range_falls_back_when_start_is_missing() -> None:
    body = "No start.\n\nEnd here. ^r-r"
    assert extract_block(body, "r-r", _BLP) == "End here. ^r-r"


def test_extract_block_missing_returns_none() -> None:
    assert extract_block("Nothing here.", "nope") is None


# ---------------------------------------------------------------------------
# Clean-up helpers
# ---------------------------------------------------------------------------


def test_strip_block_ids_removes_markers_but_not_code() -> None:
    content = "Text ^abc\n| a |\n^tbl\n> ^quoted\n```\nx ^keep\n```\n2^3 stays"
    assert strip_block_ids(content) == "Text\n| a |\n```\nx ^keep\n```\n2^3 stays"


def test_strip_obsidian_comments_outside_code() -> None:
    content = "a %% hidden %% b\n%%\nblock\n%%\n```\n%% code %%\n```"
    assert strip_obsidian_comments(content) == "a  b\n\n```\n%% code %%\n```"


def test_rebase_headings_moves_topmost_to_level() -> None:
    assert rebase_headings("# A\n\n## B", 3) == "### A\n\n#### B"
    assert rebase_headings("#### A\n\n##### B", 2) == "## A\n\n### B"
    assert rebase_headings("##### A\n\n###### B", 6) == "###### A\n\n###### B"
    assert rebase_headings("no headings", 4) == "no headings"


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


def test_embed_whole_note_strips_frontmatter(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Shared.md", "---\ntags: [x]\n---\nShared body.\n")
    page = _write(vault / "Page.md", "![[Shared]]\n")
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b"))
    assert "Shared body." in out
    assert "tags" not in out


def test_embed_block_by_vault_path(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Area" / "Info.md", "| K | V |\n| - | - |\n| a | 1 |\n^ids\n")
    _write(vault / "Other" / "Info.md", "Wrong file. ^ids\n")
    page = _write(vault / "Docs" / "Page" / "Page.md", "Intro\n\n![[Area/Info#^ids]]\n")
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b"))
    assert "| a | 1 |" in out
    assert "Wrong file" not in out


def test_embed_in_callout_keeps_quote_prefix(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Note.md", "Line one\nline two ^p\n")
    page = _write(vault / "Page.md", "> [!note]\n> ![[Note#^p]]\n")
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b"))
    assert "> Line one\n> line two ^p" in out


def test_inline_embed_is_joined_into_line(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Note.md", "Short text. ^s\n")
    page = _write(vault / "Page.md", "Value: ![[Note#^s]] (see note)\n")
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b"))
    assert out.strip() == "Value: Short text. ^s (see note)"


@pytest.mark.parametrize(
    ("line", "first", "indent"),
    [("* ![[Src#^risk]]", "* ", "  "), ("  1. ![[Src#^risk]]", "  1. ", "     ")],
)
def test_block_embed_of_a_callout_in_a_list_item_stays_a_block(
    tmp_path: Path, line: str, first: str, indent: str
) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Src.md", "# Src\n\n> [!WARNING] Risk\n> Body text.\n^risk\n")
    page = _write(vault / "Doc" / "Doc.md", f"List:\n\n{line}\n")
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b"))
    assert f"{first}> [!WARNING] Risk\n{indent}> Body text." in out
    converted = convert_callouts(out)
    assert f"{first}::: {{.callout .callout-warning" in converted
    assert f"{indent}Body text." in converted
    assert "> " not in converted


def test_embedded_headings_sit_below_context(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Spec.md", "# Spec\n\n## Colors\n\nRed.\n\n### Shades\n\nDark.\n")
    page = _write(vault / "Page.md", "## Section\n\n### Detail\n\n![[Spec#Colors]]\n")
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b"))
    assert "#### Colors" in out
    assert "##### Shades" in out


def test_embedded_headings_without_context_go_below_page_title(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Spec.md", "# Spec\n\nBody.\n")
    page = _write(vault / "Page.md", "![[Spec]]\n")
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b"))
    assert "## Spec" in out


def test_nested_embeds_resolve_from_source_note(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Lib" / "img" / "pic.png", "")
    _write(vault / "pic.png", "")
    _write(vault / "Lib" / "Inner.md", "Inner text.\n")
    _write(vault / "Lib" / "Outer.md", "Outer text.\n\n![[Inner]]\n\n![[pic.png]]\n")
    page = _write(vault / "Docs" / "Page.md", "![[Outer]]\n")
    build = tmp_path / "b"
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, build))
    assert "Outer text." in out
    assert "Inner text." in out
    assert "![](pic.png){.doc-image}" in out
    assert (build / "pic.png").exists()


def test_recursive_embed_is_stopped(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "A.md", "A text.\n\n![[B]]\n")
    _write(vault / "B.md", "B text.\n\n![[A]]\n")
    page = _write(vault / "Page.md", "![[A]]\n")
    messages: list[str] = []
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b", messages))
    assert out.count("A text.") == 1
    assert out.count("B text.") == 1
    assert "*A*" in out
    assert any("recursive embed" in m for m in messages)


def test_deep_embed_chain_hits_depth_limit(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    count = MAX_EMBED_DEPTH + 3
    for i in range(count):
        _write(vault / f"N{i}.md", f"Level {i}.\n\n![[N{i + 1}]]\n")
    _write(vault / f"N{count}.md", "Bottom.\n")
    page = _write(vault / "Page.md", "![[N0]]\n")
    messages: list[str] = []
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b", messages))
    assert f"Level {MAX_EMBED_DEPTH - 1}." in out
    assert "Bottom." not in out
    assert any("nests deeper" in m for m in messages)


def test_unresolved_embeds_render_placeholder_and_warn(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Note.md", "Text.\n")
    page = _write(vault / "Page.md", "![[Missing#^x]]\n\n![[Note#^nope]]\n\n![[Note#No Heading]]\n")
    messages: list[str] = []
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b", messages))
    assert "*Missing#^x*" in out
    assert "*Note#^nope*" in out
    assert "*Note#No Heading*" in out
    assert len(messages) == 3
    assert all(m.startswith("  Warning:") for m in messages)


def test_image_and_attachment_embeds_are_left_alone(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "file.pdf", "")
    page = _write(vault / "Page.md", "![[pic.png]]\n![[file.pdf]]\n")
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b"))
    assert out == page.read_text()


def test_embed_inside_code_block_is_not_expanded(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Note.md", "Text.\n")
    page = _write(vault / "Page.md", "```\n![[Note]]\n```\n")
    out = expand_note_embeds(page.read_text(), page, _ctx(vault, tmp_path / "b"))
    assert out == page.read_text()


def test_embed_inside_inline_code_is_not_expanded(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault / "Note.md", "Text. ^id\n")
    content = "Write `![[Note#^id]]` or ``a `![[Note]]` b``.\n\n`![[Missing]]`\n\n![[Note#^id]]\n"
    page = _write(vault / "Page.md", content)
    messages: list[str] = []
    out = expand_note_embeds(content, page, _ctx(vault, tmp_path / "b", messages))
    kept = "Write `![[Note#^id]]` or ``a `![[Note]]` b``.\n\n`![[Missing]]`\n\n"
    assert out == f"{kept}\nText. ^id\n\n"
    assert messages == []


def test_strip_block_ids_and_comments_skip_inline_code() -> None:
    assert strip_block_ids("Use `x ^abc` like this ^real") == "Use `x ^abc` like this"
    assert strip_block_ids("`^abc`") == "`^abc`"
    assert strip_obsidian_comments("a `%% kept %%` b %% gone `x` %%") == "a `%% kept %%` b "


def test_process_page_expands_embeds_and_strips_markers(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(
        vault / "Lib" / "Spec.md",
        "## Part\n\n%% %% ^r\n\nFirst. ^one\n\n| a | b |\n| - | - |\n^tbl\n\n^r-r\n\nAfter.\n",
    )
    page_file = _write(
        vault / "Doc" / "Doc.md", "Own text. ^own\n\n## Embedded\n\n![[Spec#^r-r]]\n"
    )
    node = PageNode(folder=page_file.parent, name="Doc", depth=1, md_file=page_file)
    build = tmp_path / "b"
    build.mkdir()
    out = process_page(node, {}, build, vault, plugins=list(_BLP), vault_index=VaultIndex(vault))
    assert "Own text." in out
    assert "First." in out
    assert "| a | b |" in out
    assert "After." not in out
    assert "^" not in out
    assert "%%" not in out
