"""Tests of the Dataview plugin: grammar, values, functions, page index, queries and output.

Part of the expression cases are ported from the tests of obsidian-dataview
(``tests/fixtures/dataview/expressions.json``, MIT License).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from obsidian_pdf_exporter.core.steps.base import PageContext
from obsidian_pdf_exporter.core.vault_index import VaultIndex
from obsidian_pdf_exporter.plugins.dataview import DataviewPlugin
from obsidian_pdf_exporter.plugins.dataview.context import Context
from obsidian_pdf_exporter.plugins.dataview.context import EvalError
from obsidian_pdf_exporter.plugins.dataview.engine import DataviewError
from obsidian_pdf_exporter.plugins.dataview.engine import Engine
from obsidian_pdf_exporter.plugins.dataview.functions import cyrb53
from obsidian_pdf_exporter.plugins.dataview.functions import js_regex
from obsidian_pdf_exporter.plugins.dataview.functions import js_split
from obsidian_pdf_exporter.plugins.dataview.index import DataviewIndex
from obsidian_pdf_exporter.plugins.dataview.index import extract_full_line_field
from obsidian_pdf_exporter.plugins.dataview.index import extract_inline_fields
from obsidian_pdf_exporter.plugins.dataview.index import parse_csv
from obsidian_pdf_exporter.plugins.dataview.luxon import DateTime
from obsidian_pdf_exporter.plugins.dataview.luxon import FixedZone
from obsidian_pdf_exporter.plugins.dataview.luxon import from_format
from obsidian_pdf_exporter.plugins.dataview.luxon import set_now
from obsidian_pdf_exporter.plugins.dataview.parse import EXPRESSION
from obsidian_pdf_exporter.plugins.dataview.parse import QueryError
from obsidian_pdf_exporter.plugins.dataview.parse import parse_field
from obsidian_pdf_exporter.plugins.dataview.parse import parse_inline_value
from obsidian_pdf_exporter.plugins.dataview.parse import parse_query
from obsidian_pdf_exporter.plugins.dataview.render import Renderer
from obsidian_pdf_exporter.plugins.dataview.render import list_spans_to_html
from obsidian_pdf_exporter.plugins.dataview.values import Link
from obsidian_pdf_exporter.plugins.dataview.values import Settings
from obsidian_pdf_exporter.plugins.dataview.values import canonicalize_var_name
from obsidian_pdf_exporter.plugins.dataview.values import compare_value
from obsidian_pdf_exporter.plugins.dataview.values import js_number
from obsidian_pdf_exporter.plugins.dataview.values import locale_compare
from obsidian_pdf_exporter.plugins.dataview.values import render_minimal_duration
from obsidian_pdf_exporter.plugins.dataview.values import to_string

FIXTURES = Path(__file__).parent.parent / "fixtures" / "dataview"


def evaluate(text: str, data: dict | None = None) -> object:
    return Context().evaluate(parse_field(text), data)


@pytest.fixture(autouse=True)
def _frozen_now() -> object:
    set_now(DateTime.from_object(2026, 3, 15, 10, 30).ts)
    yield
    set_now(None)


# ---- Expressions ported from Dataview's own tests ---------------------------


_CASES = json.loads((FIXTURES / "expressions.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize(("suite", "expr", "kind", "expected"), _CASES)
def test_ported_expression(suite: str, expr: str, kind: str, expected: object) -> None:
    result = evaluate(expr)
    if kind == "eval":
        expected = evaluate(expected)
    assert compare_value(result, expected) == 0, (suite, expr, result, expected)


# ---- Grammar ----------------------------------------------------------------


def test_query_header_shapes() -> None:
    q = parse_query('TABLE WITHOUT ID file.link AS "Name", due\nFROM "A"')
    assert q.header["showId"] is False
    assert [f.name for f in q.header["fields"]] == ["Name", "due"]
    q = parse_query('LIST WITHOUT ID file.name + "!"\nFROM #x')
    assert q.header["showId"] is False
    assert q.header["format"] is not None
    assert parse_query("TASK").header == {"type": "task"}
    assert parse_query("CALENDAR file.day").header["field"].name == "file.day"
    assert parse_query("table").header["fields"] == []


def test_data_commands_keep_their_order_and_repeat() -> None:
    q = parse_query(
        "TABLE x\nFROM #a\n// a comment\nWHERE x > 1\nSORT x DESC, y\nGROUP BY x\n"
        "FLATTEN rows AS r\nWHERE r\nLIMIT 3"
    )
    assert [op["type"] for op in q.operations] == [
        "where",
        "sort",
        "group",
        "flatten",
        "where",
        "limit",
    ]
    assert [f["direction"] for f in q.operations[1]["fields"]] == ["descending", "ascending"]


def test_sources_combine_with_and_or_and_negation() -> None:
    q = parse_query('LIST FROM ("A" or #b) and -"A/Old" AND !#c')
    src = q.source
    assert src.kind == "binaryop"
    assert src.op == "&"
    assert src.right.kind == "negate"
    assert parse_query("LIST FROM [[Note]]").source.kind == "link"
    out = parse_query("LIST FROM outgoing([[Note|x]])").source
    assert (out.kind, out.value, out.incoming) == ("link", "Note", False)
    assert parse_query('LIST FROM csv("data.csv")').source.kind == "csv"


def test_parse_errors_look_like_parsimmon() -> None:
    with pytest.raises(QueryError) as e:
        parse_query("TABLE x FROM")
    text = str(e.value)
    assert text.startswith("Error: \n-- PARSING FAILED ---")
    assert "> 1 | TABLE x FROM" in text


def test_grammar_quirks_of_dataview() -> None:
    assert evaluate("due-date", {"due-date": 3}) == 3
    assert evaluate("a - b", {"a": 5, "b": 2}) == 3
    with pytest.raises(QueryError):
        parse_field("trueValue")
    with pytest.raises(QueryError):
        parse_field("where")
    assert evaluate("1 = 1 AND 2 = 2") is True
    assert evaluate('"a" + 1') == "a1"
    assert evaluate('"ab" * 2') == "abab"
    assert evaluate("!true") is False


def test_inline_values() -> None:
    assert parse_inline_value("14") == 14
    assert parse_inline_value('"yes,"') == "yes,"
    assert parse_inline_value("[[test]], [[test2]]")[1].path == "test2"
    assert parse_inline_value('1, 2, 3, "hello"') == [1, 2, 3, "hello"]
    assert parse_inline_value("False") is False
    assert parse_inline_value("hello, world") == "hello, world"
    assert parse_inline_value("") is None
    assert isinstance(parse_inline_value("2024-05-01"), DateTime)
    assert parse_inline_value("2 h").values["hours"] == 2
    assert (
        EXPRESSION.inline_field.parse("[[yes, no, and maybe]]").value.path == "yes, no, and maybe"
    )


# ---- Inline fields (ported from Dataview's parse.inline tests) -----------------


def test_extract_inline_fields() -> None:
    assert extract_inline_fields("") == []
    assert extract_inline_fields("[]") == []
    assert extract_inline_fields("[key:value]") == []
    f = extract_inline_fields("[key::value]")[0]
    assert (f.key, f.value, f.start, f.start_value, f.end, f.wrapping) == (
        "key",
        "value",
        0,
        6,
        12,
        "[",
    )
    two = extract_inline_fields("[key:: value] and so thus, [key2:: value2]")
    assert [(x.key, x.start, x.end) for x in two] == [("key", 0, 13), ("key2", 27, 42)]
    assert extract_inline_fields("[[[[hello:: 16]]")[0].value == "16"
    assert extract_inline_fields("This is some text. [key:: [value]]")[0].value == "[value]"
    escaped = extract_inline_fields("Hello? [key! :: \\[value]")[0]
    assert (escaped.key, escaped.value) == ("key!", "\\[value")
    assert extract_inline_fields("      - [ ] Huh! [p:: 1]")[0].key == "p"
    html = extract_inline_fields('[link:: <a href="Page">Value</a>]')[0]
    assert html.value == '<a href="Page">Value</a>'


@pytest.mark.parametrize(
    ("line", "key", "value"),
    [
        ("- [ ] testTask 🗓️2022-07-14", "due", "2022-07-14"),
        ("- [ ] testTask 🗓2022-07-14", "due", "2022-07-14"),
        (" - [ ] testTask \u27952022-07-25", "created", "2022-07-25"),
        (" - [ ] testTask 🛫2022-07-21", "start", "2022-07-21"),
        (" - [ ] testTask ⏳2022-07-24", "scheduled", "2022-07-24"),
        (" - [x] testTask ✅ 2022-07-24", "completion", "2022-07-24"),
    ],
)
def test_task_emoji_fields(line: str, key: str, value: str) -> None:
    f = extract_inline_fields(line, include_task_fields=True)[0]
    assert (f.key, f.value) == (key, value)


def test_full_line_fields() -> None:
    assert extract_full_line_field("**Due Date**:: 2024-01-01").key == "Due Date"
    assert extract_full_line_field("## Status:: done").key == "Status"
    assert extract_full_line_field("no field here") is None


def test_key_normalisation() -> None:
    assert canonicalize_var_name("Due Date") == "due-date"
    assert canonicalize_var_name("Prüfung  am!") == "prüfung-am"
    assert canonicalize_var_name("📅 Date") == "📅-date"


# ---- Values -----------------------------------------------------------------


def test_numbers_print_like_javascript() -> None:
    assert [js_number(v) for v in (0.1 + 0.2, 1e21, 1e-7, 1.5e-5, 2**53, -0.0000012, 4.0)] == [
        "0.30000000000000004",
        "1e+21",
        "1e-7",
        "0.000015",
        "9007199254740992",
        "-0.0000012",
        "4",
    ]
    assert evaluate("1 / 0") == math.inf
    assert evaluate("7 % 3") == 1
    assert evaluate("10 / 4") == 2.5


def test_strings_sort_like_locale_compare() -> None:
    words = ["b", "A", "a", "_x", "-y", "1", "Zeta", "éclair", "eclair", "Éclair", "alpha beta"]
    words += ["alpha-beta", "alphabet"]
    expected = "_x|-y|1|a|A|alpha beta|alpha-beta|alphabet|b|eclair|éclair|Éclair|Zeta"
    import functools

    assert "|".join(sorted(words, key=functools.cmp_to_key(locale_compare))) == expected


def test_mixed_types_order_by_type_name_and_null_first() -> None:
    values = ["x", 3, None, True, Link.file("a.md"), [1], {"a": 1}]
    import functools

    ordered = sorted(values, key=functools.cmp_to_key(compare_value))
    assert [type(v).__name__ for v in ordered] == [
        "NoneType",
        "list",
        "bool",
        "Link",
        "int",
        "dict",
        "str",
    ]


def test_to_string_of_values() -> None:
    s = Settings()
    assert to_string(None, s) == "\\-"
    assert to_string([1, [2, 3]], s) == "1, [2, 3]"
    assert to_string({"a": 1}, s) == "{ a: 1 }"
    assert to_string(Link.file("F/Note.md"), s) == "[[F/Note.md|Note]]"
    assert (
        to_string(Link.header("F/Note.md", "My Heading!"), s)
        == "[[F/Note.md#My Heading|Note > My Heading]]"
    )
    assert to_string(DateTime.from_object(2024, 5, 1), s) == "May 01, 2024"
    assert to_string(DateTime.from_object(2024, 5, 1, 14, 5), s) == "2:05 PM - May 01, 2024"


# ---- Dates and durations ----------------------------------------------------


def test_date_literals_and_arithmetic() -> None:
    assert evaluate("date(today)").to_format("yyyy-MM-dd HH:mm") == "2026-03-15 00:00"
    assert evaluate("date(now)").hour == 10
    assert evaluate("date(sow)").to_format("ccc yyyy-MM-dd") == "Mon 2026-03-09"
    assert evaluate("date(eom)").to_format("yyyy-MM-dd HH:mm:ss") == "2026-03-31 23:59:59"
    assert evaluate("date(2024-01-31) + dur(1 month)").to_format("yyyy-MM-dd") == "2024-02-29"
    assert evaluate("date(2024-03-01) - date(2024-01-15)").values["months"] == 1
    diff = evaluate("date(2024-03-10) - date(2024-03-01)")
    assert render_minimal_duration(diff) == "1 week, 2 days"
    assert evaluate("(date(2024-03-10) - date(2024-03-01)).days") == 9
    assert evaluate("date(2024-05-06).weekday") == 1
    assert evaluate("date(2024-05-06).weekyear") == 19
    assert evaluate('date("2024-05-01T10:00:00Z")').zone.name == "UTC"
    assert evaluate('date("not a date")') is None


def test_durations() -> None:
    assert evaluate("dur(1h30m)").values == {"hours": 1, "minutes": 30}
    assert render_minimal_duration(evaluate("dur(90 minutes)")) == "1 hour, 30 minutes"
    assert render_minimal_duration(evaluate("dur(10 days)")) == "1 week, 3 days"
    assert render_minimal_duration(evaluate("dur(1 day) * 1.5")) == "1 day, 12 hours"
    assert evaluate("dur(2 days) > dur(1 day)") is True
    assert evaluate('durationformat(dur(3 hours 5 minutes), "h:mm")') == "3:05"


def test_luxon_formatting_tokens() -> None:
    d = DateTime.from_object(2024, 5, 1, 14, 7, 9, 45, zone=FixedZone(120))
    assert d.to_format("yyyy-MM-dd'T'HH:mm:ss.SSS ZZ") == "2024-05-01T14:07:09.045 +02:00"
    assert d.to_format("EEEE, MMMM d, yy h a") == "Wednesday, May 1, 24 2 PM"
    assert d.to_format("DDD") == "May 1, 2024"
    assert d.to_format("o 'week' W q") == "122 week 18 2"
    assert from_format("01.05.2024", "dd.MM.yyyy").to_format("yyyy-MM-dd") == "2024-05-01"
    assert from_format("May 3 2024 5:30 pm", "MMMM d yyyy h:mm a").hour == 17
    assert from_format("nope", "yyyy") is None


# ---- Functions --------------------------------------------------------------


def test_javascript_string_semantics() -> None:
    assert js_split("a1b2c3", js_regex(r"\d")) == ["a", "b", "c", ""]
    assert js_split("abc", js_regex("")) == ["a", "b", "c"]
    assert js_split("a,b,,c", js_regex(","), 2) == ["a", "b"]
    assert js_split("a1b", js_regex(r"(\d)")) == ["a", "1", "b"]
    assert (
        evaluate(r'regexreplace("2024-05-01", "(\d+)-(\d+)", "$2/$1 $& $$")')
        == "05/2024 2024-05 $-01"
    )
    assert evaluate('replace("a.b.c", ".", "-")') == "a-b-c"
    assert evaluate('padleft("7", 3, "0")') == "007"
    assert evaluate('padright("ab", 5, "xy")') == "abxyx"
    assert evaluate('substring("hello", 3, 1)') == "el"
    assert evaluate('truncate("hello world", 8)') == "hello..."
    assert evaluate('containsword("Hello world", "WORLD")') is True
    assert evaluate('containsword("Hello worlds", "world")') is False
    assert evaluate('regexmatch("\\d+", "123")') is True
    assert evaluate('split("a, b,c", ", ?")') == ["a", "b", "c"]


def test_utility_functions() -> None:
    assert evaluate("round(2.5)") == 3
    assert evaluate("round(-2.5)") == -2
    assert evaluate("round(1.005, 2)") == 1
    assert evaluate("round(1.2345, 2)") == 1.23
    assert evaluate('currencyformat(-1234.5, "EUR")') == "-€1,234.50"
    assert evaluate('currencyformat(3, "CHF")') == "CHF\u00a03.00"
    assert evaluate('currencyformat(1234.5, "JPY")') == "¥1,235"
    assert cyrb53("seed") == 3845622891912142
    assert cyrb53("seed", 7) == 4762367489971957
    assert evaluate('hash("seed", "text")') == 5527096208375726
    assert cyrb53("ä€😀", 3) == 2490804396587393
    assert evaluate("default(null, 5)") == 5
    assert evaluate("default(list(1, null), 5)") == [1, 5]
    assert evaluate("ldefault(list(1, null), 5)") == [1, None]
    assert evaluate('choice(true, "a", "b")') == "a"
    assert evaluate("typeof(date(today))") == "date"
    assert evaluate("typeof((x) => x)") == "function"
    assert evaluate('dateformat(date(2024-05-01), "yyyy LLL")') == "2024 May"
    assert evaluate("striptime(date(now)).hour") == 0
    meta = evaluate("meta([[Folder/Note#Part|shown]])")
    assert meta == {
        "display": "shown",
        "embed": False,
        "path": "Folder/Note",
        "subpath": "Part",
        "type": "header",
    }
    assert evaluate("meta(![[img.png]]).embed") is True
    assert evaluate('display("**bold** [[A|b]]")') == "bold b"


def test_array_functions_with_lambdas() -> None:
    assert evaluate("map(list(1, 2, 3), (x) => x * 2)") == [2, 4, 6]
    assert evaluate("filter(list(1, 2, 3), (x) => x > 1)") == [2, 3]
    assert evaluate("reduce(list(1, 2, 3), (a, b) => a + b)") == 6
    assert evaluate('reduce(list("a", "b"), "+")') == "ab"
    assert evaluate("sum(list(1, 2, 3))") == 6
    assert evaluate("average(list(1, 2, 3, 4))") == 2.5
    assert evaluate("min(3, 1, 2)") == 1
    assert evaluate("max(list(3, 1, 2))") == 3
    assert evaluate("minby(list(3, 1, 2), (x) => 0 - x)") == 3
    assert evaluate("sort(list(3, 1, 2), (x) => 0 - x)") == [3, 2, 1]
    assert evaluate("unique(list(3, 1, 3, 2))") == [1, 2, 3]
    assert evaluate("nonnull(list(1, null, 2))") == [1, 2]
    assert evaluate("firstvalue(list(null, 4, 5))") == 4
    assert evaluate('join(list(1, "a"), " | ")') == "1 | a"
    assert evaluate("any(list(0, 1))") is True
    assert evaluate("none(list(0, 1), (x) => x > 5)") is True
    assert evaluate("flat(list(1, list(2, list(3))))") == [1, 2, [3]]
    assert evaluate("slice(list(1, 2, 3, 4), -2)") == [3, 4]
    assert evaluate('extract(object("a", 1, "b", 2), "b")') == {"b": 2}
    assert evaluate('icontains(list("Apple"), "apple")') is True
    assert evaluate('econtains(list("hello"), "he")') is False
    assert evaluate("length(list(1, 2))") == 2
    assert evaluate('lower(list("A", "B"))') == ["a", "b"]
    assert evaluate("rows.x", {"rows": [{"x": 1}, {"x": 2}]}) == [1, 2]
    assert evaluate("row.x", {"x": 4}) == 4


def test_errors_of_expressions() -> None:
    with pytest.raises(EvalError, match="No implementation found for 'number \\+ null'"):
        evaluate("1 + null")
    with pytest.raises(EvalError, match="Unrecognized function name 'nope'"):
        evaluate("nope(1)")
    with pytest.raises(EvalError, match="No implementation of 'lower' found"):
        evaluate("lower(1)")


# ---- Vault ------------------------------------------------------------------

_NOTES = {
    "Projects/Alpha.md": (
        "---\ntags: [project, team/a]\nstatus: active\nDue Date: 2026-05-01\npriority: 2\n"
        'aliases: First\nowner: "[[People/Ana]]"\n---\n# Alpha\n\nEffort:: 3 days\n'
        "Text with [inline:: 5] and (hidden:: yes). See [[Beta]].\n\n"
        "## Work\n- [ ] Write spec 📅 2026-04-01 #todo\n    - [x] Draft ✅ 2026-03-01\n"
        "- [/] Review [due:: 2026-04-10]\n- note item [kind:: info]\n"
    ),
    "Projects/Beta.md": (
        "---\ntags: project\nstatus: done\nDue Date: 2026-02-01\npriority: 1\n---\n"
        "Links to [[Alpha]] and ![[pic.png]].\n- [x] Ship it\n"
    ),
    "Projects/Archive/Gamma.md": "---\ntags: [project]\nstatus: active\npriority: 3\n---\nOld.\n",
    "People/Ana.md": "---\nrole: Lead\n---\nAna works on [[Alpha]].\n",
    "Journal/2026-03-14.md": "Journal entry.\n",
    "Report.md": "Report page.\n",
    "data.csv": "name,count,ok\nx,1,true\ny,2.5,false\n",
    "pic.png": "",
}


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    for rel, text in _NOTES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def engine(vault: Path) -> Engine:
    return Engine(DataviewIndex(VaultIndex(vault)))


def test_page_object(engine: Engine) -> None:
    page = engine.index.page("Projects/Alpha.md")
    f = page["file"]
    assert (f["name"], f["folder"], f["ext"]) == ("Alpha", "Projects", "md")
    assert f["tags"] == ["#todo", "#project", "#team/a", "#team"]
    assert f["etags"] == ["#todo", "#project", "#team/a"]
    assert f["aliases"] == ["First"]
    assert [lk.path for lk in f["outlinks"]] == ["People/Ana.md", "Projects/Beta.md"]
    assert [lk.path for lk in f["inlinks"]] == ["People/Ana.md", "Projects/Beta.md"]
    assert page["due-date"].to_format("yyyy-MM-dd") == "2026-05-01"
    assert page["Due Date"] == page["due-date"]
    assert page["effort"].values["days"] == 3
    assert (page["inline"], page["hidden"]) == (5, "yes")
    assert page["owner"].path == "People/Ana.md"
    assert page["kind"] == "info"
    assert f["frontmatter"]["Due Date"] == "2026-05-01"
    assert isinstance(f["mtime"], DateTime)
    assert f["mday"].hour == 0
    assert engine.index.page("Journal/2026-03-14.md")["file"]["day"].day == 14


def test_tasks_and_lists(engine: Engine) -> None:
    f = engine.index.page("Projects/Alpha.md")["file"]
    tasks = f["tasks"]
    assert [t["text"] for t in tasks] == [
        "Write spec 📅 2026-04-01 #todo",
        "Draft ✅ 2026-03-01",
        "Review [due:: 2026-04-10]",
    ]
    spec, draft, review = tasks
    assert spec["due"].to_format("yyyy-MM-dd") == "2026-04-01"
    assert spec["children"][0]["text"] == draft["text"]
    assert spec["fullyCompleted"] is False
    assert draft["completion"].day == 1
    assert draft["parent"] == spec["line"]
    assert review["status"] == "/"
    assert review["checked"] is True
    assert review["completed"] is False
    assert spec["section"].subpath == "Work"
    assert spec["tags"] == ["#todo"]
    assert len(f["lists"]) == 4


def test_sources(engine: Engine) -> None:
    def paths(src: str, origin: str = "Report.md") -> list[str]:
        return engine.matching_paths(parse_query("LIST FROM " + src).source, origin)

    assert paths("#project") == [
        "Projects/Alpha.md",
        "Projects/Archive/Gamma.md",
        "Projects/Beta.md",
    ]
    assert paths("#team") == ["Projects/Alpha.md"]
    assert paths('"Projects" and -"Projects/Archive"') == ["Projects/Alpha.md", "Projects/Beta.md"]
    assert paths('"People" or #team') == ["People/Ana.md", "Projects/Alpha.md"]
    assert paths("[[Alpha]]") == ["People/Ana.md", "Projects/Beta.md"]
    assert paths("outgoing([[Alpha]])") == ["People/Ana.md", "Projects/Beta.md"]
    assert paths('"Projects/Beta"') == ["Projects/Beta.md"]
    assert paths('"Missing"') == []
    with pytest.raises(DataviewError, match="Could not find file"):
        engine.matching_paths(parse_query("LIST FROM outgoing([[pic.png]])").source, "Report.md")


def _table(engine: Engine, text: str, origin: str = "Report.md") -> tuple[list, list]:
    r = engine.execute_table(parse_query(text), origin)
    return r.names, r.values


def test_table_where_sort_limit(engine: Engine) -> None:
    names, rows = _table(
        engine, 'TABLE status, priority FROM #project WHERE status = "active" SORT priority DESC'
    )
    assert names == ["File", "status", "priority"]
    assert [r[0].path for r in rows] == ["Projects/Archive/Gamma.md", "Projects/Alpha.md"]
    _, rows = _table(
        engine, "TABLE WITHOUT ID file.name FROM #project SORT status, priority DESC LIMIT 2"
    )
    assert rows == [["Gamma"], ["Alpha"]]
    _, rows = _table(
        engine,
        "TABLE file.name FROM #project WHERE file.name != this.file.name",
        "Projects/Beta.md",
    )
    assert len(rows) == 2


def test_group_by_and_flatten(engine: Engine) -> None:
    names, rows = _table(
        engine, "TABLE rows.file.name AS Names, length(rows) FROM #project GROUP BY status"
    )
    assert names == ["status", "Names", "length(rows)"]
    assert rows == [["active", ["Alpha", "Gamma"], 2], ["done", ["Beta"], 1]]
    _, rows = _table(engine, "TABLE WITHOUT ID t FROM #project FLATTEN file.etags AS t SORT t")
    assert [r[0] for r in rows] == ["#project", "#project", "#project", "#team/a", "#todo"]
    names, rows = _table(engine, "TABLE x FROM #project GROUP BY status FLATTEN rows.priority AS x")
    assert names[0] == "status"
    assert len(rows) == 3


def test_rows_with_errors_are_dropped_and_all_failing_fails(engine: Engine) -> None:
    query = 'TABLE priority FROM #project WHERE priority + choice(status = "done", 1, null) > 0'
    _, rows = _table(engine, query)
    assert [r[0].path for r in rows] == ["Projects/Beta.md"]
    with pytest.raises(DataviewError, match="Every row during operation 'where' failed"):
        _table(engine, "TABLE priority FROM #project WHERE nothing + 1")
    with pytest.raises(DataviewError, match="limit should be a number"):
        _table(engine, 'TABLE x FROM #project LIMIT "a"')


def test_list_task_calendar_csv(engine: Engine) -> None:
    lst = engine.execute_list(parse_query("LIST status FROM #project SORT file.name"), "Report.md")
    assert (lst.values[0].key.path, lst.values[0].value) == ("Projects/Alpha.md", "active")
    plain = engine.execute_list(parse_query("LIST WITHOUT ID status FROM #project"), "Report.md")
    assert sorted(plain.values) == ["active", "active", "done"]
    tasks = engine.execute_task(parse_query('TASK FROM "Projects" WHERE !completed'), "Report.md")
    assert [t["text"].split(" ")[0] for t in tasks.tasks] == ["Write", "Review"]
    grouped = engine.execute_task(
        parse_query('TASK FROM "Projects" GROUP BY file.link'), "Report.md"
    )
    assert [g["key"].path for g in grouped.tasks] == ["Projects/Alpha.md", "Projects/Beta.md"]
    cal = engine.execute_calendar(parse_query('CALENDAR file.day FROM "Journal"'), "Report.md")
    assert cal.entries[0]["date"].day == 14
    _, rows = _table(engine, 'TABLE name, count FROM csv("data.csv")')
    assert rows[1][1:] == ["y", 2.5]
    assert parse_csv("a,b\n1,true\n")[0] == {"a": 1, "b": True}


def test_link_indexing_and_this(engine: Engine) -> None:
    ctx = engine.context("Projects/Alpha.md")
    assert ctx.evaluate(parse_field("[[Beta]].status")) == "done"
    assert ctx.evaluate(parse_field("this.owner.role")) == "Lead"
    assert ctx.evaluate(parse_field('meta(link("Beta")).path')) == "Projects/Beta.md"
    assert ctx.evaluate(parse_field("[[Missing]].status")) is None
    assert ctx.evaluate(parse_field("date([[2026-03-14]])")).day == 14


# ---- Output -----------------------------------------------------------------


def test_table_output() -> None:
    r = Renderer(Settings())
    rows = [[Link.file("A/Note.md"), None, ["x", "y|z"], DateTime.from_object(2024, 5, 1), True]]
    out = r.table(["File", "a", "b", "c", "d"], rows)
    lines = out.splitlines()
    assert lines[0] == '| File <span class="dataview+small-text">1</span> | a | b | c | d |'
    assert "[[A/Note.md\\|Note]]" in lines[2]
    assert "| \\- |" in lines[2]
    assert "y\\|z" in lines[2]
    assert "May 01, 2024" in lines[2]
    assert lines[2].endswith("| true |")
    html = list_spans_to_html(lines[2])
    assert '<ul class="dataview dataview-ul dataview-result-list-ul">' in html


def test_empty_results_and_settings() -> None:
    r = Renderer(Settings())
    assert "No results to show for table query." in r.table(["File"], [])
    assert r.list([]).endswith("No results to show for list query.</p></div>")
    quiet = Renderer(Settings(warnOnEmptyResult=False, renderNullAs="n/a", showResultCount=False))
    assert quiet.list([]) == ""
    assert quiet.table(["File"], [[None]]) == "| File |\n|---|\n| n/a |"
    custom = Renderer(Settings(defaultDateFormat="dd.MM.yyyy"))
    assert custom.lit(DateTime.from_object(2024, 5, 1)) == "01.05.2024"


def test_multiline_values_in_cells() -> None:
    r = Renderer(Settings())
    out = r.lit("Intro\n- one\n- two\n    - deep\nafter")
    assert out.startswith('Intro<span class="dataview-md-ul">')
    html = list_spans_to_html(out)
    assert html == "Intro<ul><li>one</li><li>two<ul><li>deep</li></ul></li></ul>after"


def test_task_output_nests_children() -> None:
    r = Renderer(Settings())
    parent = {
        "path": "a.md",
        "line": 1,
        "text": "Parent",
        "task": True,
        "status": " ",
        "children": [],
    }
    child = {"path": "a.md", "line": 2, "parent": 1, "text": "Child", "task": True, "status": "x"}
    child["children"] = []
    parent["children"] = [child]
    assert r.tasks([parent, child]) == "- [ ] Parent\n    - [x] Child"
    grouped = r.tasks([{"key": Link.file("a.md"), "rows": [parent]}])
    assert grouped.startswith(
        '#### [[a.md\\|a]] <span class="dataview+small-text">1</span> {.unnumbered .unlisted}'
    )
    assert "::: {.dataview .result-group}" in grouped


def test_calendar_output() -> None:
    r = Renderer(Settings())
    out = r.calendar(
        [{"date": DateTime.from_object(2026, 3, 14), "link": Link.file("J/2026-03-14.md")}]
    )
    assert "March 2026" in out
    assert "| Sun | Mon | Tue | Wed | Thu | Fri | Sat |" in out
    assert "14</span><br>[[J/2026-03-14.md\\|2026-03-14]]" in out


# ---- Plugin -----------------------------------------------------------------


def _run(
    vault: Path, text: str, *, page: str = "Report.md", options: dict | None = None
) -> tuple[str, list[str]]:
    messages: list[str] = []
    source = vault / page
    ctx = PageContext(
        vault_root=vault,
        page_folder=source.parent,
        frontmatter={},
        options=options or {},
        vault_index=VaultIndex(vault),
        source_file=source,
        log=messages.append,
    )
    return DataviewPlugin().process_markdown(text, ctx), messages


def test_plugin_renders_blocks_in_callouts_and_keeps_other_code(vault: Path) -> None:
    text = (
        "> [!note] Projects\n> ```dataview\n> LIST FROM #team\n> ```\n\n"
        "````markdown\n```dataview\nLIST\n```\n````\n"
    )
    out, messages = _run(vault, text)
    assert "> - [[Projects/Alpha.md\\|Alpha]]" in out
    assert "````markdown\n```dataview\nLIST\n```\n````" in out
    assert messages == []


def test_plugin_reports_errors(vault: Path) -> None:
    out, messages = _run(vault, "```dataview\nTABLE x FROM\n```\n")
    assert out.startswith('<pre class="dataview+dataview-error">Dataview: Error: ')
    assert messages[0].startswith("  Warning: cannot parse a Dataview query in Report.md")


def test_inline_queries_and_settings_from_data_json(vault: Path) -> None:
    settings = vault / ".obsidian" / "plugins" / "dataview"
    settings.mkdir(parents=True)
    (settings / "data.json").write_text(
        json.dumps({"inlineQueryPrefix": "dv:", "defaultDateFormat": "yyyy-MM-dd"}),
        encoding="utf-8",
    )
    out, _ = _run(vault, "Due `dv: [[Alpha]].due-date`, me `dv: this.file.name`, `= 1`.")
    assert 'Due <span class="dataview+dataview-inline-query">2026-05-01</span>' in out
    assert ">Report</span>" in out
    assert "`= 1`" in out
    out, _ = _run(vault, "`= this.file.name`", options={"dataview.inlineQueryPrefix": "="})
    assert ">Report</span>" in out


def test_pretty_inline_fields(vault: Path) -> None:
    out, _ = _run(vault, "Text [due:: 2026-04-10] and (hidden:: [[Beta]]) and `[x:: 1]`.")
    assert '<span class="dataview+inline-field-key">due</span>' in out
    assert '<span class="dataview+inline-field-value">April 10, 2026</span>' in out
    assert '<span class="dataview+inline-field-standalone-value">[[Projects/Beta.md' not in out
    assert '<span class="dataview+inline-field-standalone-value">[[Beta\\|Beta]]</span>' in out
    assert "`[x:: 1]`" in out
    off, _ = _run(vault, "[a:: 1]", options={"dataview.prettyRenderInlineFields": "false"})
    assert off == "[a:: 1]"


def test_plugin_html_hook_turns_spans_into_lists() -> None:
    html = '<html><head></head><body><td><span class="dataview-md-ul+x">'
    html += '<span class="dataview-md-li">a</span></span></td></body></html>'
    out = DataviewPlugin().process_html(html, None)  # type: ignore[arg-type]
    assert '<ul class="x"><li>a</li></ul>' in out
    assert '<style id="dataview">' in out


# ---- DataviewJS -------------------------------------------------------------


def test_dataviewjs_api(vault: Path) -> None:
    code = (
        "```dataviewjs\n"
        "const pages = dv.pages('#project').where(p => p.status == 'active')\n"
        "    .sort(p => p.priority, 'desc');\n"
        "dv.header(2, 'Active');\n"
        "dv.table(['Name', 'Prio'], pages.map(p => [p.file.link, p.priority]));\n"
        "dv.list(pages.file.name);\n"
        "dv.paragraph(`${dv.current().file.name}: ${dv.date('2026-01-02').toFormat('dd.MM.')}`);\n"
        "const grouped = dv.pages('#project').groupBy(p => p.status)\n"
        "    .map(g => g.key + '=' + g.rows.length);\n"
        "dv.span(grouped.join(', '));\n"
        "const q = await dv.query('LIST FROM #team');\n"
        "dv.paragraph(q.value.values.length + ' ' + dv.func.lower('ABC') + ' '\n"
        "    + dv.evaluate('1 + 2').value);\n"
        "dv.taskList(dv.page('Alpha').file.tasks.where(t => !t.completed));\n"
        "```\n"
    )
    out, messages = _run(vault, code)
    assert messages == []
    assert "## Active {.unnumbered .unlisted}" in out
    assert "| [[Projects/Archive/Gamma.md\\|Gamma]] | 3 |" in out
    assert "- Gamma\n- Alpha" in out
    assert "Report: 02.01." in out
    assert "active=2, done=1" in out
    assert "1 abc 3" in out
    assert "- [ ] Write spec" in out


def test_dataviewjs_errors_sandbox_and_inline(vault: Path) -> None:
    out, messages = _run(vault, "```dataviewjs\nrequire('fs').writeFileSync('x', 'y')\n```\n")
    assert "Evaluation Error: ReferenceError: require is not defined" in out
    assert messages[0].startswith("  Warning: a DataviewJS block failed")
    out, _ = _run(
        vault, "```dataviewjs\ndv.paragraph(typeof fetch + ' ' + typeof XMLHttpRequest)\n```\n"
    )
    assert out.strip() == "undefined undefined"
    out, _ = _run(
        vault, "```dataviewjs\nwhile (true) {}\n```\n", options={"dataview.js-timeout": "0.5"}
    )
    assert "took longer than 0.5 s" in out
    out, _ = _run(vault, "Count `$= dv.pages('#project').length`.")
    assert out == "Count 3."
    loaded, _ = _run(
        vault,
        "```dataviewjs\nconst t = await dv.io.load('Projects/Beta.md');\n"
        "dv.span(t.length > 10)\n```\n",
    )
    assert loaded.strip() == "<span>true</span>"
    disabled, _ = _run(
        vault, "```dataviewjs\ndv.span(1)\n```\n", options={"dataview.enableDataviewJs": "false"}
    )
    assert "Dataview JS queries are disabled" in disabled


def test_end_to_end_query_shapes(vault: Path) -> None:
    text = (
        '```dataview\nTABLE WITHOUT ID file.link AS "Project", rows.status\nFROM #project\n'
        "GROUP BY file.link\nSORT rows.priority ASC\n```\n\n"
        '```dataview\nTASK\nFROM "Projects"\nWHERE !completed\nGROUP BY file.link\n```\n\n'
        "```dataview\nLIST rows.file.link\nFROM #project\nGROUP BY status\n```\n"
    )
    out, messages = _run(vault, text)
    assert messages == []
    assert '| Project <span class="dataview+small-text">3</span> | rows.status |' in out
    assert "#### [[Projects/Alpha.md\\|Alpha]]" in out
    assert "- active: <span" in out


def test_index_cache_follows_the_vault_index_object(tmp_path: Path) -> None:
    """Two indexes in sequence (as in a redline) never share their Dataview pages."""
    root = tmp_path / "vault"
    (root / "Projects").mkdir(parents=True)
    note = root / "Projects" / "Alpha.md"
    query = '```dataview\nTABLE status FROM "Projects"\n```\n'
    outputs = []
    for status in ("active", "done", "archived"):
        note.write_text(f"---\nstatus: {status}\n---\n", encoding="utf-8")
        ctx = PageContext(
            vault_root=root,
            page_folder=root,
            frontmatter={},
            vault_index=VaultIndex(root),
            source_file=root / "Report.md",
        )
        outputs.append(DataviewPlugin().process_markdown(query, ctx))
        del ctx
    assert [
        ("| " + s + " |") in out
        for s, out in zip(("active", "done", "archived"), outputs, strict=True)
    ] == [True] * 3
