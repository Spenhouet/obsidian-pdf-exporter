"""Tests for the layered pipeline: dialect, core steps and plugin hooks."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import pytest

from obsidian_pdf_exporter.core.assemble import process_page
from obsidian_pdf_exporter.core.dialect import Dialect
from obsidian_pdf_exporter.core.pipeline import markdown_dialect
from obsidian_pdf_exporter.core.pipeline import run_html
from obsidian_pdf_exporter.core.pipeline import run_markdown
from obsidian_pdf_exporter.core.steps import CORE_STEPS
from obsidian_pdf_exporter.core.steps import DocumentContext
from obsidian_pdf_exporter.core.steps import PageContext
from obsidian_pdf_exporter.core.steps import Step
from obsidian_pdf_exporter.core.steps import core_steps
from obsidian_pdf_exporter.core.tree import PageNode
from obsidian_pdf_exporter.plugins import ObsidianPlugin
from obsidian_pdf_exporter.plugins import active_plugins
from obsidian_pdf_exporter.plugins import available_plugins
from obsidian_pdf_exporter.plugins.drawio import DrawioPlugin

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Step ordering
# ---------------------------------------------------------------------------

_MARKDOWN_ORDER = [
    "frontmatter",
    "plugins",
    "html_comments",
    "embeds",
    "obsidian_comments",
    "block_ids",
    "callouts",
    "heading_links",
    "wiki_links",
    "bracket_links",
    "image_captions",
    "title_heading",
    "heading_levels",
    "plugin_code_blocks",
]

_HTML_ORDER = [
    "base_css",
    "empty_table_headers",
    "column_widths",
    "svg_images",
    "heading_links",
    "tasks",
    "math",
    "wide_tables",
    "plugins",
]


def _overrides(step: Step, hook: str) -> bool:
    return getattr(type(step), hook) is not getattr(Step, hook)


def test_core_steps_are_listed_in_priority_order() -> None:
    priorities = [cls.priority for cls in CORE_STEPS]
    assert priorities == sorted(priorities)
    assert len(set(priorities)) == len(priorities)


def test_step_names_are_unique() -> None:
    names = [cls.name for cls in CORE_STEPS]
    assert len(set(names)) == len(names)


def test_markdown_steps_run_in_documented_order() -> None:
    names = [s.name for s in core_steps() if _overrides(s, "process_markdown")]
    assert names == _MARKDOWN_ORDER


def test_html_steps_run_in_documented_order() -> None:
    steps = sorted(core_steps(), key=lambda s: s.html_order)
    names = [s.name for s in steps if _overrides(s, "process_html")]
    assert names == _HTML_ORDER


def test_embedded_steps() -> None:
    names = [s.name for s in core_steps() if s.embedded]
    assert names == ["plugins", "html_comments", "embeds", "wiki_links"]


class _Append(Step):
    def __init__(self, name: str, priority: int, html_priority: int | None = None) -> None:
        self.name = name
        self.priority = priority
        self.html_priority = html_priority

    def process_markdown(self, content: str, context: PageContext) -> str:
        return content + self.name

    def process_html(self, html: str, context: DocumentContext) -> str:
        return html + self.name


def test_run_markdown_sorts_by_priority() -> None:
    steps = [_Append("c", 30), _Append("a", 10), _Append("b", 20)]
    assert run_markdown("", PageContext(), steps) == "abc"


def test_run_html_sorts_by_html_priority(tmp_path: Path) -> None:
    steps = [_Append("a", 10, html_priority=30), _Append("b", 20), _Append("c", 30, 5)]
    assert run_html("", DocumentContext(build_dir=tmp_path), steps) == "cba"


def test_process_page_accepts_custom_steps(tmp_path: Path) -> None:
    page = tmp_path / "Page.md"
    page.write_text("---\nkey: v\n---\nBody ==x==", encoding="utf-8")
    node = PageNode(folder=tmp_path, name="Page", depth=1, md_file=page)
    steps = [s for s in core_steps() if s.name == "frontmatter"]
    assert process_page(node, {}, tmp_path, steps=steps) == "Body ==x=="


# ---------------------------------------------------------------------------
# Dialect
# ---------------------------------------------------------------------------


def test_dialect_extend_skips_duplicates() -> None:
    d = Dialect(extensions=("a",), disabled=("x",), args=("--one",))
    d = d.extend(["b", "a", "b"], ["--two", "--one"])
    assert d.reader == "markdown+a+b-x"
    assert d.args == ("--one", "--two")


def test_dialect_without_drops_extensions() -> None:
    d = Dialect(extensions=("a", "mark"), disabled=())
    assert d.optional == ("mark",)
    assert d.without(["mark"]).reader == "markdown+a"


@pytest.mark.parametrize(("line_breaks", "hard"), [("hard", True), ("soft", False)])
def test_steps_contribute_to_dialect(tmp_path: Path, line_breaks: str, hard: bool) -> None:
    ctx = DocumentContext(build_dir=tmp_path, options={"line_breaks": line_breaks})
    dialect = markdown_dialect(ctx, core_steps())
    for ext in ("raw_html", "lists_without_preceding_blankline", "fenced_divs", "mark"):
        assert ext in dialect.extensions
    assert dialect.disabled == ("raw_tex",)
    assert ("hard_line_breaks" in dialect.extensions) is hard
    assert "--mathml" in dialect.args


# ---------------------------------------------------------------------------
# Plugin hooks
# ---------------------------------------------------------------------------


class _HtmlPlugin(ObsidianPlugin):
    name = "html_test"

    def process_html(self, html: str, context: DocumentContext) -> str:
        return html.replace("<p>", '<p class="seen">')


class _MarkdownOnlyPlugin(ObsidianPlugin):
    """A plugin written before the HTML, SVG and block hooks existed."""

    name = "markdown_only"

    def process_markdown(self, content: str, context: object) -> str:
        return content.replace("old", "new")


class _DuckPlugin:
    """A plugin that does not subclass ObsidianPlugin and only has the old hook."""

    name = "duck"
    priority = 100

    def process_markdown(self, content: str, context: object) -> str:
        return content + " duck"


def test_plugin_html_hook_runs_in_html_stage(tmp_path: Path) -> None:
    ctx = DocumentContext(build_dir=tmp_path, plugins=[_HtmlPlugin()])
    html = run_html("<head></head><p>x</p>", ctx, core_steps())
    assert '<p class="seen">x</p>' in html


def test_plugin_html_hook_runs_after_core_html_steps(tmp_path: Path) -> None:
    seen: list[str] = []

    class Spy(ObsidianPlugin):
        name = "spy"

        def process_html(self, html: str, context: DocumentContext) -> str:
            seen.append(html)
            return html

    ctx = DocumentContext(build_dir=tmp_path, plugins=[Spy()])
    run_html('<head></head><ul><li><input type="checkbox" /> a</li></ul>', ctx, core_steps())
    assert "obsidian-pdf-exporter-base" in seen[0]
    assert "task-checkbox" in seen[0]


def test_old_plugins_keep_working(tmp_path: Path) -> None:
    page = tmp_path / "Page.md"
    page.write_text("old text", encoding="utf-8")
    node = PageNode(folder=tmp_path, name="Page", depth=1, md_file=page)
    plugins: list[Any] = [_MarkdownOnlyPlugin(), _DuckPlugin()]
    assert process_page(node, {}, tmp_path, plugins=plugins) == "new text duck"
    ctx = DocumentContext(build_dir=tmp_path, plugins=plugins)
    assert run_html("<p>x</p>", ctx, core_steps()).endswith("<p>x</p>")


def test_plugin_svg_hook_sees_inlined_svgs(tmp_path: Path) -> None:
    (tmp_path / "d.svg").write_text('<svg viewBox="0 0 1 1"><g/></svg>', encoding="utf-8")

    class Svg(ObsidianPlugin):
        name = "svg_test"

        def process_svg(self, svg: str, context: DocumentContext) -> str:
            return svg.replace("<g/>", "<g id='seen'/>")

    ctx = DocumentContext(build_dir=tmp_path, plugins=[Svg()])
    html = run_html('<head></head><img src="d.svg" />', ctx, core_steps())
    assert "<g id='seen'/>" in html


def test_drawio_cleanup_only_runs_with_the_plugin(tmp_path: Path) -> None:
    svg = (
        '<svg viewBox="0 0 10 10"><switch><foreignObject><div>x</div></foreignObject>'
        "<a><text>Text is not SVG - cannot display</text></a></switch></svg>"
    )
    (tmp_path / "d.svg").write_text(svg, encoding="utf-8")
    html = '<head></head><img src="d.svg" />'
    with_plugin = run_html(html, DocumentContext(tmp_path, plugins=[DrawioPlugin()]), core_steps())
    without = run_html(html, DocumentContext(tmp_path), core_steps())
    assert "cannot display" not in with_plugin
    assert "cannot display" in without


def test_plugin_block_hook_is_asked_first(tmp_path: Path) -> None:
    (tmp_path / "Lib.md").write_text("Para ^a\n", encoding="utf-8")
    page = tmp_path / "Page.md"
    page.write_text("![[Lib#^a]]\n\n![[Lib#^custom]]", encoding="utf-8")

    class Blocks(ObsidianPlugin):
        name = "blocks_test"

        def extract_block(self, body: str, block_id: str) -> str | None:
            return "From plugin." if block_id == "custom" else None

    node = PageNode(folder=tmp_path, name="Page", depth=1, md_file=page)
    out = process_page(node, {}, tmp_path, tmp_path, plugins=[Blocks()])
    assert out.split() == ["Para", "From", "plugin."]


def test_community_plugins_are_registered() -> None:
    names = available_plugins()
    assert {"block_link_plus", "drawio"} <= set(names)
    enabled = {p.name for p in active_plugins(disabled={"drawio", "block_link_plus"})}
    assert not enabled & {"drawio", "block_link_plus"}
