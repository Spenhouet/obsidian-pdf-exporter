"""Tests for the Templater plugin."""

from __future__ import annotations

from pathlib import Path

import pytest

from obsidian_pdf_exporter.core import exporter
from obsidian_pdf_exporter.core.assemble import process_page
from obsidian_pdf_exporter.core.exporter import RedlineRequest
from obsidian_pdf_exporter.core.exporter import export_redline
from obsidian_pdf_exporter.core.tree import PageNode
from obsidian_pdf_exporter.plugins import PluginContext
from obsidian_pdf_exporter.plugins import active_plugins
from obsidian_pdf_exporter.plugins import available_plugins
from obsidian_pdf_exporter.plugins.templater import TemplaterPlugin
from obsidian_pdf_exporter.plugins.templater.plugin import strip_tags
from obsidian_pdf_exporter.templates import load_template

TEMPLATE = """\
<%*
const ids = ["A-1", "B-2"];
const name = `${ids[0]}-note`;
if (tp.file.folder(true) === "Records") {
    await tp.file.move(`Records/${name}`);
}
-%>
---
id: <% tp.file.title %>
tags:
  - template
---

## Overview

Created on <% tp.date.now("YYYY-MM-DD") %>.
"""


def _plugin(content: str, frontmatter: dict | None = None) -> tuple[str, dict]:
    ctx = PluginContext(vault_root=None, page_folder=Path("/var/empty"), frontmatter={})
    ctx.frontmatter = frontmatter or {}
    out = TemplaterPlugin().process_markdown(content, ctx)
    return out, ctx.frontmatter


def test_templater_is_registered_and_runs_first() -> None:
    assert "templater" in available_plugins()
    assert active_plugins()[0].name == "templater"
    assert "templater" not in {p.name for p in active_plugins(disabled={"templater"})}


@pytest.mark.parametrize(
    "tag",
    [
        "<% tp.file.title %>",
        "<%* tR += 'x' %>",
        "<%+ tp.file.last_modified_date() %>",
        "<%-* let a = 1 %>",
        "<%_ tp.date.now() %>",
        "<%*\nconst a = 1;\nconst b = 2;\n%>",
    ],
)
def test_every_kind_of_tag_is_removed(tag: str) -> None:
    assert strip_tags(f"Before {tag} after.").replace("  ", " ") == "Before after."


def test_dash_removes_one_newline_on_its_side() -> None:
    assert strip_tags("a\n\n<%- x %>\n\nb") == "a\n\n\nb"
    assert strip_tags("a\n\n<% x -%>\n\nb") == "a\n\n\nb"
    assert strip_tags("a\n<%- x -%>\nb") == "ab"


def test_underscore_removes_all_whitespace_on_its_side() -> None:
    assert strip_tags("a \n\n <%_ x %>\n\nb") == "a\n\nb"
    assert strip_tags("a\n\n<% x _%> \n\n b") == "a\n\nb"


def test_backticks_inside_a_tag_do_not_end_it() -> None:
    assert strip_tags("<%* const s = `${a}`; -%>\nText `code`.") == "Text `code`."


def test_tags_in_inline_code_and_code_blocks_stay() -> None:
    content = "Use `<% tp.file.title %>` here.\n\n```js\n<%* tR += 'x' %>\n```\n"
    assert _plugin(content)[0] == content


def test_unclosed_tag_stays() -> None:
    assert strip_tags("a <% b") == "a <% b"


def test_frontmatter_after_a_leading_tag_is_read() -> None:
    out, fm = _plugin(TEMPLATE)
    assert fm == {"id": None, "tags": ["template"]}
    assert out.startswith("## Overview")
    assert "Created on ." in out
    assert "<%" not in out
    assert "%>" not in out


def test_frontmatter_already_read_is_kept() -> None:
    out, fm = _plugin("<% x -%>\n---\na: 1\n---\nBody", {"b": 2})
    assert fm == {"b": 2}
    assert out == "---\na: 1\n---\nBody"


def test_export_hides_the_script_and_the_frontmatter(tmp_path: Path) -> None:
    page = tmp_path / "Template.md"
    page.write_text(TEMPLATE, encoding="utf-8")
    node = PageNode(folder=tmp_path, name="Template", depth=1, md_file=page)
    out = process_page(node, {}, tmp_path, tmp_path, plugins=active_plugins())
    assert "<%" not in out
    assert "tags:" not in out
    assert "---" not in out
    assert "Overview" in out


def test_redline_hides_the_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    old.write_text(TEMPLATE, encoding="utf-8")
    new.write_text(TEMPLATE.replace("Created on", "Made on"), encoding="utf-8")
    monkeypatch.setattr(exporter, "html_to_pdf", lambda _html, out, **_kw: out.write_bytes(b"%PDF"))
    output = tmp_path / "out" / "redline.pdf"
    output.parent.mkdir()
    export_redline(
        RedlineRequest(
            root=new,
            output=output,
            template=load_template("redline"),
            from_path=old,
            debug=True,
        ),
        log=lambda _msg: None,
    )
    md = (output.parent / "_build_redline" / "redline_assembled.md").read_text(encoding="utf-8")
    assert "<del>Created</del><ins>Made</ins>" in md
    assert "&lt;%" not in md
    assert "<%" not in md
    assert "tags:" not in md
