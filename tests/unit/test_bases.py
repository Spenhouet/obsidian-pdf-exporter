"""Tests for Obsidian Bases: expressions, filters, formulas and views."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core.assemble import process_page
from obsidian_pdf_exporter.core.bases import BaseView
from obsidian_pdf_exporter.core.bases import VaultFiles
from obsidian_pdf_exporter.core.bases import load_base
from obsidian_pdf_exporter.core.bases.evaluate import Evaluator
from obsidian_pdf_exporter.core.bases.expr import parse
from obsidian_pdf_exporter.core.bases.values import Unsupported
from obsidian_pdf_exporter.core.bases.values import parse_duration
from obsidian_pdf_exporter.core.tree import PageNode
from obsidian_pdf_exporter.core.vault_index import VaultIndex

if TYPE_CHECKING:
    from pathlib import Path

BOOKS = {
    "Library/Dune.md": (
        '---\ntags: [book, fiction/scifi]\nauthor: "[[Frank Herbert]]"\nprice: 12.5\n'
        "pages: 412\nstatus: reading\nstarted: 2024-03-01\n---\n# Dune\n\nSee [[Arrakis]].\n"
    ),
    "Library/Emma.md": (
        "---\ntags: [book]\nauthor: Jane Austen\nprice: 8\npages: 474\nstatus: done\n"
        "started: 2023-11-20\n---\nA #classic novel.\n"
    ),
    "Library/Old/Walden.md": (
        "---\ntags: book\nauthor: Henry David Thoreau\nprice: 5\npages: 352\nstatus: done\n---\n"
    ),
    "Library/Notes.md": "---\ntags: [note]\n---\nNot a book. ```#nottag``` \n",
    "Library/cover.png": "",
    "Frank Herbert.md": "---\nborn: 1920\n---\n",
}

BASE = """\
filters:
  and:
    - file.hasTag("book")
    - file.ext == "md"
formulas:
  price_per_page: (price / pages * 100).toFixed(2)
  label: 'if(status == "done", "Read", "Open") + " - " + author'
properties:
  note.price:
    displayName: Price
  formula.price_per_page:
    displayName: Cents per page
views:
  - type: table
    name: All books
    order:
      - file.name
      - author
      - price
      - formula.price_per_page
    sort:
      - property: price
        direction: DESC
    summaries:
      price: Sum
  - type: list
    name: Done
    filters:
      and:
        - status == "done"
        - not:
            - file.inFolder("Library/Old")
    order:
      - file.name
      - formula.label
  - type: table
    name: By status
    groupBy:
      property: status
      direction: ASC
    order:
      - file.name
      - pages
    limit: 2
"""


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    for rel, text in BOOKS.items():
        path = vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (vault / "Books.base").write_text(BASE, encoding="utf-8")
    return vault


def _view(vault: Path, base: str = BASE, this: str | None = None) -> tuple[BaseView, list[str]]:
    files = VaultFiles(VaultIndex(vault))
    record = files.record(vault / this) if this else None
    messages: list[str] = []
    return BaseView(load_base(base), files, record, messages.append), messages


def _export(vault: Path, text: str) -> tuple[str, list[str]]:
    page = vault / "Page.md"
    page.write_text(text, encoding="utf-8")
    build = vault.parent / "build"
    build.mkdir(exist_ok=True)
    messages: list[str] = []
    node = PageNode(folder=vault, name="Page", md_file=page, depth=1)
    out = process_page(node, {}, build, vault, vault_index=VaultIndex(vault), log=messages.append)
    return out, messages


def _eval(vault: Path, expression: str, file: str = "Library/Dune.md") -> object:
    files = VaultFiles(VaultIndex(vault))
    ev = Evaluator(
        files=files.records,
        resolve=files.resolve,
        formulas={"double": "pages * 2"},
        this=files.record(vault / "Library/Emma.md"),
        now=datetime.datetime(2024, 5, 1, 12, 0, 0),
    )
    return ev.evaluate(expression, files.record(vault / file))


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("price * 2", 25.0),
        ("pages % 100", 12),
        ('"a" + 1', "a1"),
        ("(price / 2).toFixed(1)", "6.2"),
        ("(2.5).round()", 3),
        ("(2.3333).round(2)", 2.33),
        ('status == "reading" && price > 10', True),
        ('status != "reading" || "fallback"', "fallback"),
        ('!file.hasTag("classic")', True),
        ('file.hasTag("fiction")', True),  # nested tag fiction/scifi
        ('file.hasTag("#book", "x")', True),
        ('file.inFolder("Library")', True),
        ('file.inFolder("Lib")', False),
        ("file.name", "Dune.md"),
        ("file.basename", "Dune"),
        ("file.ext", "md"),
        ("file.folder", "Library"),
        ("file.path", "Library/Dune.md"),
        ('file.hasLink("Arrakis")', True),
        ('file.hasProperty("price")', True),
        ("file.tags", ["#book", "#fiction/scifi"]),
        ("note.price", 12.5),
        ('note["status"]', "reading"),
        ("formula.double", 824),
        ('if(price > 100, "expensive", "cheap")', "cheap"),
        ('if(price > 100, "expensive")', None),
        ("missing", None),
        ("missing.isEmpty()", True),
        ('"hello".contains("ell")', True),
        ('"a,b,c,d".split(",", 3)', ["a", "b", "c"]),
        ('"a:b:c".replace(/:/, "-")', "a-b:c"),
        ('"a:b:c".replace(/:/g, "-")', "a-b-c"),
        ('"John Smith".replace(/(\\w+) (\\w+)/, "$2, $1")', "Smith, John"),
        ('"hello world".title()', "Hello World"),
        ('"  hi ".trim().length', 2),
        ("[1, 2, 3, 4].filter(value > 2)", [3, 4]),
        ("[1, 2, 3].map(value + index)", [1, 3, 5]),
        ("[1, 2, 3].reduce(acc + value, 0)", 6),
        ("[3, 1, 2].sort()", [1, 2, 3]),
        ('[1, [2, 3]].flat().unique().join("-")', "1-2-3"),
        ("[1,2,3].containsAny(3, 4)", True),
        ('list("x")', ["x"]),
        ("max(1, 5, 3) - min(4, 2)", 3),
        ('number("3.5") + 1', 4.5),
        ('"x".isType("string")', True),
        ('/abc/.matches("xxabcx")', True),
        ('date("2024-12-01") + "1M" == date("2025-01-01")', True),
        ('(date("2024-01-31") + "1 month").format("YYYY-MM-DD")', "2024-02-29"),
        ('started.format("DD.MM.YYYY")', "01.03.2024"),
        ('started < date("2024-04-01")', True),
        ('started > "2024-02-01"', True),
        ("started.year", 2024),
        ('today() - "1 week" > started', True),
        ('now().format("YYYY-MM-DD HH:mm")', "2024-05-01 12:00"),
        ('(date("2024-01-02") - date("2024-01-01")) / 86400000', 1),
        ('author == link("Frank Herbert")', True),
        ("author.asFile().properties.born", 1920),
        ("this.file.name", "Emma.md"),
        ("this.author", "Jane Austen"),
        ("file == this", False),
        ("started.relative()", "2 months ago"),
        ('price > 10 ? "high" : "low"', "high"),
    ],
)
def test_expressions(tmp_path: Path, expression: str, expected: object) -> None:
    assert _eval(_vault(tmp_path), expression) == expected


def test_hyphenated_property_names(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "Task.md").write_text("---\ndue-date: 2024-01-05\nx: 5\ny: 2\n---\n", encoding="utf-8")
    assert _eval(vault, 'due-date.format("YYYY")', "Task.md") == "2024"
    assert _eval(vault, "x-y", "Task.md") == 3


@pytest.mark.parametrize(
    "expression", ['html("<b>x</b>")', "file.unknownField", '"x".nope()', "price +", "a $ b"]
)
def test_unsupported_expressions_raise(tmp_path: Path, expression: str) -> None:
    with pytest.raises(Unsupported):
        _eval(_vault(tmp_path), expression)


def test_parse_precedence() -> None:
    assert parse("a || b && c") == (
        "bin",
        "||",
        ("name", "a"),
        ("bin", "&&", ("name", "b"), ("name", "c")),
    )
    assert parse("1 + 2 * 3")[1] == "+"
    assert parse("-x.y")[0] == "unary"


def test_durations() -> None:
    assert parse_duration("1d").ms == 86_400_000
    assert parse_duration("2 weeks").ms == 14 * 86_400_000
    assert parse_duration("1M").months == 1
    assert parse_duration("1y 2h").months == 12
    assert parse_duration("soon") is None


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def test_table_view_filters_sorts_and_names_columns(tmp_path: Path) -> None:
    view, messages = _view(_vault(tmp_path))
    out = view.render()
    lines = out.split("\n")
    assert lines[0] == "| file name | author | Price | Cents per page |"
    assert lines[2] == "| [[Dune]] | [[Frank Herbert]] | 12.5 | 3.03 |"
    assert lines[3] == "| [[Emma]] | Jane Austen | 8 | 1.69 |"
    assert lines[4] == "| [[Walden]] | Henry David Thoreau | 5 | 1.42 |"
    assert lines[5] == "|  |  | Sum: 25.5 |  |"
    assert "Notes" not in out
    assert "cover" not in out
    assert messages == []


def test_list_view_with_not_filter(tmp_path: Path) -> None:
    view, _ = _view(_vault(tmp_path))
    assert view.render("Done") == "- [[Emma]]: Read - Jane Austen"


def test_group_by_and_limit(tmp_path: Path) -> None:
    view, _ = _view(_vault(tmp_path))
    out = view.render("by status")
    # The limit keeps the first two files by path (Dune, Emma), then they are grouped.
    groups = out.split("\n\n")
    assert groups[0] == "*status: done*"
    assert "[[Emma]]" in groups[1]
    assert groups[2] == "*status: reading*"
    assert "[[Dune]]" in groups[3]
    assert "Walden" not in out


def test_group_order(tmp_path: Path) -> None:
    base = BASE.replace("    limit: 2\n", "    groupOrder:\n      - reading\n")
    view, _ = _view(_vault(tmp_path), base)
    out = view.render("By status")
    assert out.startswith("*status: reading*")
    assert "done" not in out


def test_unknown_view_name_falls_back_with_warning(tmp_path: Path) -> None:
    view, messages = _view(_vault(tmp_path))
    assert view.render("Nope").startswith("| file name |")
    assert messages == ["has no view named 'Nope', showing the first view"]


def test_unsupported_parts_warn_once(tmp_path: Path) -> None:
    base = """\
filters:
  and:
    - file.hasTag("book")
    - 'file.name.someFunction()'
formulas:
  pic: html("<b>x</b>")
views:
  - type: kanban
    order: [file.name, formula.pic]
"""
    view, messages = _view(_vault(tmp_path), base)
    out = view.render()
    assert out.count("[[") == 3  # the unsupported filter is ignored, all books stay
    assert messages == [
        "cannot show kanban views, shown as a table",
        "cannot evaluate the filter 'file.name.someFunction()' (string.someFunction()), "
        "the filter is ignored",
        "cannot evaluate 'formula.pic' (function html()), left empty",
    ]


def test_no_results(tmp_path: Path) -> None:
    view, _ = _view(_vault(tmp_path), 'filters: file.hasTag("nothing")\n')
    assert view.render() == "*No results.*"


def test_base_without_views_lists_all_files(tmp_path: Path) -> None:
    view, _ = _view(_vault(tmp_path), 'filters:\n  and:\n    - file.ext == "png"\n')
    assert view.render() == "| file name |\n| --- |\n| [[cover.png]] |"


def test_invalid_yaml() -> None:
    with pytest.raises(ValueError, match="YAML"):
        load_base("views: [")


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------


def test_embed_with_view_name(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    out, messages = _export(vault, "Intro.\n\n![[Books.base#Done]]\n\nEnd.\n")
    assert "- Emma: Read - Jane Austen" in out
    assert all("Link to note outside the PDF: " in m for m in messages)


def test_embed_in_callout_keeps_the_quote(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    out, _ = _export(vault, "> [!note]\n> ![[Books.base#Done]]\n")
    assert "callout-note" in out
    assert "\n- Emma: Read - Jane Austen\n:::" in out


def test_code_block_uses_this_file(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    text = (
        "---\nauthor: Jane Austen\n---\n"
        "```base\nfilters:\n  and:\n    - author == this.author\n"
        "views:\n  - type: table\n    order: [file.name, pages]\n```\n"
    )
    out, messages = _export(vault, text)
    assert "| file name | pages |" in out
    assert "Emma" in out
    assert "Dune" not in out
    assert "```" not in out
    assert all("Link to note outside the PDF: " in m for m in messages)


def test_table_links_resolve_and_keep_the_table(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    out, _ = _export(vault, "![[Books.base]]\n")
    assert "| Dune | Frank Herbert | 12.5 | 3.03 |" in out


def test_broken_base_warns_and_keeps_code(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    out, messages = _export(vault, "```base\nviews: [\n```\n")
    assert "```base" in out
    assert messages[0].startswith("  Warning: base code block in Page.md can not be read")


def test_base_inside_other_code_is_left_alone(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    text = "````markdown\n```base\nviews: []\n```\n![[Books.base]]\n````\n"
    out, _ = _export(vault, text)
    assert out == text.strip()
