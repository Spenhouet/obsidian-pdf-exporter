"""The Dataview page index: every markdown file of the vault as Dataview sees it.

Obsidian gives Dataview a metadata cache per file (sections, headings, list
items, links, embeds and tags). :func:`scan_markdown` builds the same from
the text. :func:`parse_page` then follows ``data-import/markdown-file.ts``:
frontmatter fields with their normalised keys, inline fields (``key:: value``,
``[key:: value]`` and ``(key:: value)``), list items and tasks with their
emoji dates. :meth:`PageMetadata.serialize` gives the page object of a query
with the implicit ``file.*`` fields.

File times come from the file system (``ctime`` is the birth time where the
platform has one), like the times of Obsidian Bases in this exporter. In a
fresh git checkout they are the checkout time.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import unquote

import yaml

from obsidian_pdf_exporter.plugins.dataview.luxon import DateTime
from obsidian_pdf_exporter.plugins.dataview.parse import EXPRESSION
from obsidian_pdf_exporter.plugins.dataview.parse import parse_inline_value
from obsidian_pdf_exporter.plugins.dataview.values import Link
from obsidian_pdf_exporter.plugins.dataview.values import canonicalize_var_name
from obsidian_pdf_exporter.plugins.dataview.values import deep_copy
from obsidian_pdf_exporter.plugins.dataview.values import extract_date
from obsidian_pdf_exporter.plugins.dataview.values import get_extension
from obsidian_pdf_exporter.plugins.dataview.values import get_file_title
from obsidian_pdf_exporter.plugins.dataview.values import get_parent_folder
from obsidian_pdf_exporter.plugins.dataview.values import map_leaves
from obsidian_pdf_exporter.plugins.dataview.values import match_emoji
from obsidian_pdf_exporter.plugins.dataview.values import strip_time

if TYPE_CHECKING:
    from pathlib import Path

    from obsidian_pdf_exporter.core.vault_index import VaultIndex

##############
# YAML       #
##############


class _ObsidianLoader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    """YAML as Obsidian reads it: timestamps stay text, only true/false are booleans."""


_ObsidianLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for _first in list("yYnNoOtTfF"):
    _ObsidianLoader.yaml_implicit_resolvers[_first] = [
        (tag, regexp)
        for tag, regexp in _ObsidianLoader.yaml_implicit_resolvers.get(_first, [])
        if tag != "tag:yaml.org,2002:bool"
    ]
_ObsidianLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)

_RE_FRONTMATTER = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)", re.DOTALL)


def read_frontmatter(text: str) -> tuple[dict, int]:
    """The frontmatter of a note and the number of lines it takes (0 without one)."""
    m = _RE_FRONTMATTER.match(text)
    if not m:
        return {}, 0
    lines = text[: m.end()].count("\n")
    if not text[: m.end()].endswith("\n"):
        lines += 1
    try:
        data = yaml.load(m.group(1), Loader=_ObsidianLoader)  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError:
        return {}, lines
    return (data if isinstance(data, dict) else {}), lines


##############
# Metadata   #
##############


@dataclass
class Section:
    type: str
    start: int
    end: int


@dataclass
class RawListItem:
    line: int
    end: int
    parent: int | None
    task: str | None
    block_id: str | None


@dataclass
class RawLink:
    link: str
    display: str
    line: int
    embed: bool


@dataclass
class Metadata:
    """What Obsidian's metadata cache holds for one note."""

    frontmatter: dict = field(default_factory=dict)
    frontmatter_links: list[RawLink] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    headings: list[tuple[int, str]] = field(default_factory=list)
    list_items: list[RawListItem] = field(default_factory=list)
    links: list[RawLink] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


_RE_FENCE = re.compile(r"^([ \t>]*)(`{3,}|~{3,})")
_RE_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t#]*$")
_RE_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_RE_LIST = re.compile(r"^([ \t]*)([-*+]|\d+[.)])(?:([ \t]+)(.*))?$")
_RE_TASK = re.compile(r"^\[(.)\](?:[ \t]|$)")
_RE_QUOTE = re.compile(r"^[ \t]{0,3}>")
_RE_TABLE_SEP = re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
_RE_FOOTNOTE = re.compile(r"^\[\^[^\]]+\]:")
_RE_HTML = re.compile(r"^[ \t]{0,3}<(?:/?[A-Za-z][\w-]*[\s/>]|!--)")
_RE_BLOCK_ID = re.compile(r"(?:^|\s)\^([A-Za-z0-9-]+)\s*$")
_RE_CODE_SPAN = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")
_RE_WIKI = re.compile(r"(!?)\[\[([^\[\]]+?)\]\]")
_RE_MD_LINK = re.compile(r"(!?)\[([^\]\n]*)\]\(\s*(<[^>\n]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_RE_TAG = re.compile(r"(?<![\w#&/\]])#([\w/-]*[^\W\d][\w/-]*)")
_RE_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _indent(text: str) -> int:
    return len(text.expandtabs(4)) - len(text.expandtabs(4).lstrip(" "))


def scan_markdown(text: str) -> Metadata:
    """Build Obsidian's metadata cache of a note: sections, headings, list items, links, tags."""
    meta = Metadata()
    meta.frontmatter, fm_lines = read_frontmatter(text)
    lines = text.split("\n")
    if fm_lines:
        meta.sections.append(Section("yaml", 0, fm_lines - 1))
    hidden = [False] * len(lines)  # lines whose links and tags Obsidian does not index
    i = fm_lines
    n = len(lines)
    para_start = None

    def close_paragraph(end: int) -> None:
        nonlocal para_start
        if para_start is not None:
            meta.sections.append(Section("paragraph", para_start, end))
            para_start = None

    while i < n:
        line = lines[i]
        stripped = line.strip()
        fence = _RE_FENCE.match(line)
        if fence and ">" not in fence.group(1) and _indent(fence.group(1)) < 4:
            close_paragraph(i - 1)
            marker = fence.group(2)
            start = i
            i += 1
            while i < n and not re.match(
                rf"^[ \t]*{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$", lines[i]
            ):
                i += 1
            end = min(i, n - 1)
            for k in range(start, end + 1):
                hidden[k] = True
            meta.sections.append(Section("code", start, end))
            i = end + 1
            continue
        if not stripped:
            close_paragraph(i - 1)
            i += 1
            continue
        if stripped.startswith("$$"):
            close_paragraph(i - 1)
            start = i
            if not (len(stripped) > 2 and stripped.endswith("$$")):
                i += 1
                while i < n and "$$" not in lines[i]:
                    i += 1
            end = min(i, n - 1)
            for k in range(start, end + 1):
                hidden[k] = True
            meta.sections.append(Section("math", start, end))
            i = end + 1
            continue
        if stripped.startswith("%%") and (stripped.count("%%") == 1 or stripped == "%%"):
            close_paragraph(i - 1)
            start = i
            i += 1
            while i < n and "%%" not in lines[i]:
                i += 1
            end = min(i, n - 1)
            for k in range(start, end + 1):
                hidden[k] = True
            meta.sections.append(Section("comment", start, end))
            i = end + 1
            continue
        heading = _RE_HEADING.match(line)
        if heading and (heading.group(2) is not None or line.strip("# \t") == ""):
            close_paragraph(i - 1)
            title = (heading.group(2) or "").strip()
            meta.headings.append((i, title))
            meta.sections.append(Section("heading", i, i))
            i += 1
            continue
        if _RE_RULE.match(line) and para_start is None:
            meta.sections.append(Section("thematicBreak", i, i))
            i += 1
            continue
        if _RE_QUOTE.match(line):
            close_paragraph(i - 1)
            start = i
            while i < n and lines[i].strip() and (_RE_QUOTE.match(lines[i]) or i == start):
                i += 1
            end = i - 1
            kind = "callout" if re.match(r"^[ \t]*>\s*\[!", lines[start]) else "blockquote"
            meta.sections.append(Section(kind, start, end))
            inner = [re.sub(r"^[ \t]*>[ \t]?", "", lines[k]) for k in range(start, end + 1)]
            _scan_lists(inner, start, meta, hidden=hidden)
            continue
        if _RE_LIST.match(line) and (para_start is None or _list_interrupts(line)):
            close_paragraph(i - 1)
            start = i
            i = _list_end(lines, i, hidden)
            meta.sections.append(Section("list", start, i - 1))
            _scan_lists(lines[start:i], start, meta, hidden=hidden)
            continue
        if (
            "|" in line
            and i + 1 < n
            and _RE_TABLE_SEP.match(lines[i + 1])
            and "-" in lines[i + 1]
            and para_start is None
        ):
            start = i
            i += 2
            while i < n and lines[i].strip() and "|" in lines[i]:
                i += 1
            meta.sections.append(Section("table", start, i - 1))
            continue
        if _RE_FOOTNOTE.match(line):
            close_paragraph(i - 1)
            start = i
            i += 1
            while i < n and lines[i].strip() and (lines[i].startswith((" ", "\t"))):
                i += 1
            meta.sections.append(Section("footnoteDefinition", start, i - 1))
            continue
        if _RE_HTML.match(line) and para_start is None:
            start = i
            while i < n and lines[i].strip():
                i += 1
            meta.sections.append(Section("html", start, i - 1))
            continue
        if para_start is None:
            para_start = i
        i += 1
    close_paragraph(n - 1)
    meta.sections.sort(key=lambda s: s.start)
    _scan_links_and_tags(lines, fm_lines, hidden, meta)
    for value in _strings(meta.frontmatter):
        for m in _RE_WIKI.finditer(value):
            target, display = _split_alias(m.group(2))
            meta.frontmatter_links.append(RawLink(target, display, 0, embed=False))
    return meta


def _list_interrupts(line: str) -> bool:
    """A list item may interrupt a paragraph (Obsidian, like CommonMark, allows it)."""
    return bool(_RE_LIST.match(line))


def _list_end(lines: list[str], i: int, hidden: list[bool]) -> int:
    """The line after the list that starts at ``i``."""
    n = len(lines)
    i += 1
    while i < n:
        line = lines[i]
        if not line.strip():
            j = i
            while j < n and not lines[j].strip():
                j += 1
            if j < n and (_RE_LIST.match(lines[j]) or lines[j].startswith((" ", "\t"))):
                i = j
                continue
            return i
        if _RE_LIST.match(line) or line.startswith((" ", "\t")):
            fence = _RE_FENCE.match(line)
            if fence:
                marker = fence.group(2)
                start = i
                i += 1
                while i < n and not re.match(
                    rf"^[ \t]*{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$", lines[i]
                ):
                    i += 1
                for k in range(start, min(i, n - 1) + 1):
                    hidden[k] = True
            i += 1
            continue
        if _RE_HEADING.match(line) or _RE_QUOTE.match(line) or _RE_FENCE.match(line):
            return i
        if _RE_RULE.match(line):
            return i
        i += 1  # lazy continuation of the last item
    return i


def _scan_lists(lines: list[str], offset: int, meta: Metadata, *, hidden: list[bool]) -> None:
    """Find the list items (with parent, task status and block id) in a run of lines."""
    stack: list[tuple[int, int]] = []  # (marker indent, line) of the open items
    current: RawListItem | None = None
    items: list[RawListItem] = []
    for k, line in enumerate(lines):
        number = offset + k
        m = _RE_LIST.match(line)
        if m:
            indent = _indent(m.group(1))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else None
            content = m.group(4) or ""
            task = _RE_TASK.match(content)
            current = RawListItem(number, number, parent, task.group(1) if task else None, None)
            items.append(current)
            stack.append((indent, number))
        elif current is not None and line.strip() and not hidden[number]:
            if m is None and not _RE_HEADING.match(line):
                current.end = number
        elif not line.strip():
            continue
    for item in items:
        last = lines[item.end - offset]
        bid = _RE_BLOCK_ID.search(last)
        if bid:
            item.block_id = bid.group(1)
    meta.list_items.extend(items)


def _split_alias(inner: str) -> tuple[str, str]:
    parts = re.split(r"\\?\|", inner, maxsplit=1)
    target = parts[0].strip()
    display = parts[1].strip() if len(parts) > 1 else target
    return target, display


def _scan_links_and_tags(lines: list[str], start: int, hidden: list[bool], meta: Metadata) -> None:
    in_comment = False
    for number in range(start, len(lines)):
        if hidden[number]:
            continue
        line = lines[number]
        if not in_comment and not any(c in line for c in "[#%"):
            continue
        # Drop %% comments (also across lines), HTML comments and code spans.
        visible = []
        rest = line
        while rest:
            if in_comment:
                end = rest.find("%%")
                if end < 0:
                    rest = ""
                    break
                rest = rest[end + 2 :]
                in_comment = False
            else:
                begin = rest.find("%%")
                if begin < 0:
                    visible.append(rest)
                    break
                visible.append(rest[:begin])
                rest = rest[begin + 2 :]
                in_comment = True
        text = re.sub(r"<!--.*?-->", "", "".join(visible))
        text = _RE_CODE_SPAN.sub(lambda mm: " " * len(mm.group(0)), text)
        for m in _RE_WIKI.finditer(text):
            target, display = _split_alias(m.group(2))
            meta.links.append(RawLink(target, display, number, embed=bool(m.group(1))))
        for m in _RE_MD_LINK.finditer(text):
            href = m.group(3).strip("<>")
            if _RE_SCHEME.match(href) or (href.startswith("#") and not href[1:]):
                continue
            meta.links.append(RawLink(unquote(href), m.group(2), number, embed=bool(m.group(1))))
        tag_text = _RE_WIKI.sub(" ", _RE_MD_LINK.sub(" ", text))
        meta.tags.extend("#" + m.group(1) for m in _RE_TAG.finditer(tag_text))
    meta.links.sort(key=lambda lk: lk.line)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    return []


##############
# Fields     #
##############

_RE_EMOJI_FIELDS = (
    (re.compile("\u2795\\s*(\\d{4}-\\d{2}-\\d{2})"), "created"),
    (re.compile("\U0001f6eb\\s*(\\d{4}-\\d{2}-\\d{2})"), "start"),
    (re.compile("[\u23f3\u231b]\\s*(\\d{4}-\\d{2}-\\d{2})"), "scheduled"),
    (re.compile("(?:\U0001f4c5|\U0001f4c6|\U0001f5d3\ufe0f?)\\s*(\\d{4}-\\d{2}-\\d{2})"), "due"),
    (re.compile("\u2705\\s*(\\d{4}-\\d{2}-\\d{2})"), "completion"),
)

_WRAPPERS = {"[": "]", "(": ")"}


@dataclass
class InlineField:
    key: str
    value: str
    start: int
    start_value: int
    end: int
    wrapping: str | None = None


def _find_closing(line: str, start: int, open_ch: str, close_ch: str) -> tuple[str, int] | None:
    nesting = 0
    escaped = False
    for index in range(start, len(line)):
        ch = line[index]
        if ch == "\\":
            escaped = not escaped
            continue
        if escaped:
            escaped = False
            continue
        if ch == open_ch:
            nesting += 1
        elif ch == close_ch:
            nesting -= 1
        if nesting < 0:
            return line[start:index].strip(), index + 1
        escaped = False
    return None


def _find_separator(line: str, start: int) -> tuple[str, int] | None:
    sep = line.find("::", start)
    if sep < 0:
        return None
    return line[start:sep].strip(), sep + 2


def _find_specific_inline_field(line: str, start: int) -> InlineField | None:
    open_ch = line[start]
    key = _find_separator(line, start + 1)
    if key is None:
        return None
    if any(c in key[0] for c in "[]()"):
        return None
    value = _find_closing(line, key[1], open_ch, _WRAPPERS[open_ch])
    if value is None:
        return None
    return InlineField(key[0], value[0], start, key[1], value[1], open_ch)


def extract_inline_fields(line: str, *, include_task_fields: bool = False) -> list[InlineField]:
    """``[key:: value]`` and ``(key:: value)`` fields of a line, and the task emoji dates."""
    found: list[InlineField] = []
    for wrapper in _WRAPPERS:
        index = line.find(wrapper)
        while index >= 0:
            parsed = _find_specific_inline_field(line, index)
            if parsed is None:
                index = line.find(wrapper, index + 1)
                continue
            found.append(parsed)
            index = line.find(wrapper, parsed.end)
    if include_task_fields:
        for regex, key in _RE_EMOJI_FIELDS:
            m = regex.search(line)
            if m:
                found.append(
                    InlineField(
                        key, m.group(1), m.start(), m.start() + 1, m.end(), "emoji-shorthand"
                    )
                )
    found.sort(key=lambda f: f.start)
    filtered: list[InlineField] = []
    for f in found:
        if not filtered or filtered[-1].end < f.start:
            filtered.append(f)
    return filtered


_RE_KEY_PREFIX = re.compile(r"[^0-9\w]*")
_RE_KEY_SUFFIX = re.compile(r"[_*~`]*")


def _full_line_key(raw: str) -> str | None:
    """Dataview's FULL_LINE_KEY_PARSER: drop leading markup, keep words, ``/``, ``-``."""
    pos = _RE_KEY_PREFIX.match(raw).end()
    out = []
    n = len(raw)
    while pos < n:
        e = match_emoji(raw, pos)
        if e > 0:
            out.append(raw[pos:e])
            pos = e
            continue
        ch = raw[pos]
        if ch.isalnum() or ch == "_" or ch.isspace() or ch in "/-":
            out.append(ch)
            pos += 1
        else:
            break
    pos = _RE_KEY_SUFFIX.match(raw, pos).end()
    if pos != n:
        return None
    return "".join(out)


def extract_full_line_field(text: str) -> InlineField | None:
    """A ``Key:: Value`` field that takes the whole line."""
    sep = _find_separator(text, 0)
    if sep is None:
        return None
    key = _full_line_key(sep[0])
    if key is None:
        return None
    return InlineField(key, text[sep[1] :].strip(), 0, sep[1], len(text))


def _add_field(fields: dict[str, list], key: str, value: Any) -> None:
    fields.setdefault(key, []).append(value)


def _merge_fields(target: dict[str, list], source: dict[str, list]) -> None:
    for key, values in source.items():
        if key not in target:
            target[key] = list(values)
        else:
            target[key] = target[key] + list(values)


def parse_frontmatter_value(value: Any) -> Any:
    """Frontmatter values as Dataview reads them: text that is a date, duration or link changes."""
    if value is None:
        return None
    if isinstance(value, list):
        return [parse_frontmatter_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): parse_frontmatter_value(v) for k, v in value.items()}
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        for parser in (EXPRESSION.date, EXPRESSION.duration, EXPRESSION.embed_link):
            reply = parser.parse(value)
            if reply.status:
                return reply.value
        return value
    if hasattr(value, "isoformat"):
        return parse_frontmatter_value(value.isoformat())
    return None


def finalize_fields(fields: dict[str, list]) -> dict[str, Any]:
    """Add the normalised keys (``Due Date`` gets ``due-date``) and unwrap single values."""
    normalized: dict[str, list] = {}
    for key, values in fields.items():
        norm = canonicalize_var_name(key)
        if norm == "" or norm in fields:
            continue
        normalized[norm] = normalized.get(norm, []) + list(values)
    interim: dict[str, list] = {}
    _merge_fields(interim, fields)
    _merge_fields(interim, normalized)
    return {k: v[0] if len(v) == 1 else v for k, v in interim.items()}


##############
# Pages      #
##############

_RE_LIST_ITEM = re.compile(r"^[\s>]*(\d+\.|\d+\)|\*|-|\+)\s*(\[.?\])?\s*(.*)$")
_RE_POTENTIAL_TAG = re.compile(r"#[^\s,;.:!?'\"`()\[\]{}]+")


def extract_tags(text: str) -> list[str]:
    """Tags of a list item text, Dataview's ``common.extractTags``."""
    result: list[str] = []
    for m in _RE_POTENTIAL_TAG.finditer(text):
        reply = EXPRESSION.tag.parse(m.group(0))
        if reply.status and reply.value not in result:
            result.append(reply.value)
    return result


@dataclass
class ListItem:
    symbol: str
    link: Link
    section: Link
    text: str
    line: int
    line_count: int
    list: int
    links: list[Link]
    tags: list[str]
    parent: int | None
    children: list[int]
    block_id: str | None
    fields: dict[str, list]
    task: dict | None = None
    position: dict = field(default_factory=dict)

    def first(self, *keys: str) -> Any:
        for key in keys:
            if key in self.fields:
                return self.fields[key][0]
        return None

    def serialize(self, cache: ListCache) -> dict:
        children = [c for c in (cache.get(line) for line in self.children) if c is not None]
        result: dict[str, Any] = {
            "symbol": self.symbol,
            "link": self.link,
            "section": self.section,
            "text": self.text,
            "tags": list(self.tags),
            "line": self.line,
            "lineCount": self.line_count,
            "list": self.list,
            "outlinks": list(self.links),
            "path": self.link.path,
            "children": children,
            "task": self.task is not None,
            "annotated": len(self.fields) > 0,
            "position": deep_copy(self.position),
            "subtasks": children,
            "real": self.task is not None,
            "header": self.section,
        }
        if self.parent is not None:
            result["parent"] = self.parent
        if self.block_id:
            result["blockId"] = self.block_id
        for key, values in self.fields.items():
            if key not in result:
                result[key] = values[0] if len(values) == 1 else values
        if self.task is not None:
            result.update(self.task)
            dates = {
                "created": self.first("created", "ctime", "cday"),
                "due": self.first("due", "duetime", "dueday"),
                "completion": self.first("completed", "completion", "comptime", "compday"),
                "start": self.first("start"),
                "scheduled": self.first("scheduled"),
            }
            for key, value in dates.items():
                if value is not None and value != "" and value is not False:
                    result[key] = deep_copy(value)
        return result


class ListCache:
    """Serialises list items once, so children are shared like in Dataview."""

    def __init__(self, items: list[ListItem]) -> None:
        self.items = {item.line: item for item in items}
        self.cache: dict[int, dict] = {}
        self.seen: set[int] = set()

    def get(self, line: int) -> dict | None:
        if line in self.cache:
            return self.cache[line]
        if line in self.seen or line not in self.items:
            return None
        self.seen.add(line)
        result = self.items[line].serialize(self)
        self.cache[line] = result
        return result


@dataclass
class PageMetadata:
    path: str
    ctime: DateTime
    mtime: DateTime
    size: int
    day: DateTime | None
    fields: dict[str, Any]
    tags: list[str]
    aliases: list[str]
    links: list[Link]
    lists: list[ListItem]
    frontmatter: dict

    def full_tags(self) -> list[str]:
        result: list[str] = []
        for tag in self.tags:
            sub = tag
            parts = [sub]
            while "/" in sub:
                sub = sub[: sub.rfind("/")]
                parts.append(sub)
            for p in parts:
                if p not in result:
                    result.append(p)
        return result

    def serialize(self, index: DataviewIndex) -> dict:
        cache = ListCache(self.lists)
        file: dict[str, Any] = {
            "path": self.path,
            "folder": get_parent_folder(self.path),
            "name": get_file_title(self.path),
            "link": Link.file(self.path),
            "outlinks": list(self.links),
            "inlinks": [Link.file(p) for p in index.inlinks(self.path)],
            "etags": list(self.tags),
            "tags": self.full_tags(),
            "aliases": list(self.aliases),
            "lists": [cache.get(item.line) for item in self.lists],
            "tasks": [cache.get(item.line) for item in self.lists if item.task is not None],
            "ctime": self.ctime,
            "cday": strip_time(self.ctime),
            "mtime": self.mtime,
            "mday": strip_time(self.mtime),
            "size": self.size,
            "starred": self.path in index.starred,
            "frontmatter": deep_copy(self.frontmatter),
            "ext": get_extension(self.path),
        }
        if self.day is not None:
            file["day"] = self.day
        result: dict[str, Any] = {"file": file}
        for key, value in self.fields.items():
            if key not in result:
                result[key] = value
        return result


def _split_tags_or_aliases(data: Any, on: str) -> list[str]:
    if data is None:
        return []
    if isinstance(data, list):
        return [t for item in data if item for t in _split_tags_or_aliases(item, on)]
    text = data if isinstance(data, str) else _js_text(data)
    return [t.strip() for t in re.split(on, text) if t and t.strip()]


def _js_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _find_date(path: str, fields: dict[str, list]) -> DateTime | None:
    for key, values in fields.items():
        if key.lower() not in ("date", "day"):
            continue
        if values and isinstance(values[0], DateTime):
            return values[0]
    return extract_date(get_file_title(path))


def _find_previous_header(line: int, headings: list[tuple[int, str]]) -> str | None:
    found = None
    for start, title in headings:
        if start > line:
            break
        found = title
    return found


def parse_page(
    path: str,
    text: str,
    ctime: float,
    mtime: float,
    size: int,
    normalize: Any,
) -> PageMetadata:
    """Read a note into Dataview's page metadata. ``normalize`` resolves a link path."""
    meta = scan_markdown(text)
    lines = text.split("\n")
    tags: list[str] = []
    for tag in meta.tags:
        if tag not in tags:
            tags.append(tag)
    aliases: list[str] = []
    fields: dict[str, list] = {}
    links: list[Link] = []
    fm = meta.frontmatter
    if fm:
        for key in fm:
            if str(key).lower() in ("tags", "tag"):
                for tag in _split_tags_or_aliases(fm[key], r"[,\s]+"):
                    full = tag if tag.startswith("#") else "#" + tag
                    if full not in tags:
                        tags.append(full)
        for key in fm:
            if str(key).lower() in ("alias", "aliases"):
                value = fm[key]
                if not value:
                    continue
                if isinstance(value, list):
                    aliases.extend(_js_text(v).strip() for v in value)
                else:
                    aliases.extend(_split_tags_or_aliases(value, ","))
        for key, value in fm.items():
            if key == "position":
                continue
            _add_field(fields, str(key), parse_frontmatter_value(value))
    links.extend(Link.infer(raw.link, False, raw.display) for raw in meta.frontmatter_links)
    links_by_line: dict[int, list[Link]] = {}
    for raw in [lk for lk in meta.links if not lk.embed] + [lk for lk in meta.links if lk.embed]:
        link = Link.infer(raw.link, raw.embed, raw.display)
        links.append(link)
        links_by_line.setdefault(raw.line, []).append(link)

    # List items.
    cache: dict[int, ListItem] = {}
    list_lines: set[int] = set()
    for raw in meta.list_items:
        m = _RE_LIST_ITEM.match(lines[raw.line])
        if not m:
            continue
        parts = [m.group(3), *lines[raw.line + 1 : raw.end + 1]]
        parts = [p.strip() for p in parts]
        text_nl = "\n".join(parts)
        text_sp = " ".join(parts)
        containing = next(
            (s for s in meta.sections if s.type == "list" and s.start <= raw.line <= s.end), None
        )
        section_name = _find_previous_header(raw.line, meta.headings)
        section_link = Link.file(path) if section_name is None else Link.header(path, section_name)
        closest = section_link if raw.block_id is None else Link.block(path, raw.block_id)
        item_links = []
        for line_no in range(raw.line, raw.end + 1):
            item_links.extend(links_by_line.get(line_no, []))
        item = ListItem(
            symbol=m.group(1),
            link=closest,
            section=section_link,
            text=text_nl,
            line=raw.line,
            line_count=raw.end - raw.line + 1,
            list=containing.start if containing else -1,
            links=item_links,
            tags=extract_tags(text_sp),
            parent=raw.parent if raw.parent is not None and raw.parent != raw.line else None,
            children=[],
            block_id=raw.block_id,
            fields={},
            position={
                "start": {"line": raw.line, "col": 0, "offset": 0},
                "end": {"line": raw.end, "col": len(lines[raw.end]), "offset": 0},
            },
        )
        if raw.task is not None:
            done = raw.task in ("x", "X")
            item.task = {
                "status": raw.task,
                "checked": raw.task not in ("", " "),
                "completed": done,
                "fullyCompleted": done,
            }
        for f in extract_inline_fields(text_sp, include_task_fields=True):
            _add_field(item.fields, f.key, parse_inline_value(f.value))
        if raw.task is None and not item.fields:
            full = extract_full_line_field(text_sp)
            if full is not None:
                _add_field(item.fields, full.key, parse_inline_value(full.value))
        cache[item.line] = item
        for k in range(raw.line, raw.end + 1):
            list_lines.add(k)
    literals: dict[str, list] = {}
    for item in cache.values():
        if item.parent is not None and item.parent in cache:
            cache[item.parent].children.append(item.line)
        if item.task is None:
            _merge_fields(literals, item.fields)
        if item.task is not None:
            cur: ListItem | None = item
            while cur is not None:
                if cur.task is not None:
                    cur.task["fullyCompleted"] = (
                        cur.task["fullyCompleted"] and item.task["completed"]
                    )
                cur = cache.get(cur.parent if cur.parent is not None else -1)

    # Inline fields of the other sections.
    body_fields: dict[str, list] = {}
    _merge_fields(body_fields, literals)
    for section in meta.sections:
        if section.type in ("list", "ruling"):
            continue
        for line_no in range(section.start, section.end + 1):
            if line_no >= len(lines) or line_no in list_lines:
                continue
            line = lines[line_no]
            if len(line) > 32768 or "::" not in line:
                continue
            line = line.strip()
            found = extract_inline_fields(line)
            if found:
                for f in found:
                    _add_field(body_fields, f.key, parse_inline_value(f.value))
            else:
                full = extract_full_line_field(line)
                if full is not None:
                    _add_field(body_fields, full.key, parse_inline_value(full.value))
    _merge_fields(fields, body_fields)

    # Links are stored with the path of the file they point to, when it exists.
    def norm_link(value: Any) -> Any:
        return value.with_path(normalize(value.path)) if isinstance(value, Link) else value

    links = [norm_link(lk) for lk in links]
    for item in cache.values():
        item.links = [norm_link(lk) for lk in item.links]
        item.fields = {k: [map_leaves(v, norm_link) for v in vs] for k, vs in item.fields.items()}
    fields = {k: [map_leaves(v, norm_link) for v in vs] for k, vs in fields.items()}
    raw_fm = {str(k): _plain(v) for k, v in fm.items() if k != "position"}
    return PageMetadata(
        path=path,
        ctime=DateTime.from_millis(ctime * 1000),
        mtime=DateTime.from_millis(mtime * 1000),
        size=size,
        day=_find_date(path, fields),
        fields=finalize_fields(fields),
        tags=tags,
        aliases=aliases,
        links=links,
        lists=list(cache.values()),
        frontmatter=raw_fm,
    )


def _plain(value: Any) -> Any:
    """Raw frontmatter as Obsidian keeps it (dates stay text)."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    return value


##############
# The index  #
##############


class DataviewIndex:
    """All pages of the vault, their tags and links, built once per export."""

    def __init__(self, vault: VaultIndex) -> None:
        self.vault = vault
        self.root = vault.root
        self._paths: dict[str, Path] = {}
        self._lower: dict[str, str] = {}
        for p in vault.files():
            rel = p.relative_to(self.root).as_posix()
            self._paths[rel] = p
            self._lower.setdefault(rel.lower(), rel)
        self.md_paths = sorted(
            (rel for rel in self._paths if rel.lower().endswith((".md", ".markdown"))),
            key=_path_order,
        )
        self.starred = _read_starred(self.root)
        self._pages: dict[str, PageMetadata] | None = None
        self._serialized: dict[str, dict] = {}
        self._inverse: dict[str, list[str]] = {}
        self._tags: dict[str, list[str]] = {}
        self._resolve_cache: dict[tuple[str, str], str | None] = {}
        self.settings_json = _read_settings(self.root)
        self.csv_cache: dict[str, list[dict]] = {}

    # -- pages ---------------------------------------------------------------

    @property
    def pages(self) -> dict[str, PageMetadata]:
        if self._pages is None:
            self._build()
        return self._pages  # type: ignore[return-value]

    def _build(self) -> None:
        self._pages = {}
        for rel in self.md_paths:
            path = self._paths[rel]
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                stat = path.stat()
            except OSError:
                continue
            text = text.replace("\r\n", "\n")
            page = parse_page(
                rel,
                text,
                getattr(stat, "st_birthtime", stat.st_ctime),
                stat.st_mtime,
                stat.st_size,
                lambda target, origin=rel: self.normalize(target, origin),
            )
            self._pages[rel] = page
        for rel, page in self._pages.items():
            for tag in page.full_tags():
                self._tags.setdefault(tag.lower(), []).append(rel)
            for target in dict.fromkeys(lk.path for lk in page.links):
                self._inverse.setdefault(target, []).append(rel)

    def page(self, path: str) -> dict | None:
        """The page object of ``path``, serialised once."""
        if path not in self.pages:
            return None
        if path not in self._serialized:
            self._serialized[path] = self.pages[path].serialize(self)
        return deep_copy(self._serialized[path])

    def inlinks(self, path: str) -> list[str]:
        if self._pages is None:
            self._build()
        return list(self._inverse.get(path, []))

    def tagged(self, tag: str) -> list[str]:
        if self._pages is None:
            self._build()
        return list(self._tags.get(tag.lower(), []))

    def links_of(self, path: str) -> list[str]:
        page = self.pages.get(path)
        return [] if page is None else list(dict.fromkeys(lk.path for lk in page.links))

    # -- paths ---------------------------------------------------------------

    def exists(self, path: str) -> bool:
        return path in self._paths

    def folder_exists(self, folder: str) -> bool:
        if folder in ("", "/"):
            return True
        prefix = folder.rstrip("/") + "/"
        return any(rel.startswith(prefix) for rel in self._paths) or (self.root / folder).is_dir()

    def in_folder(self, folder: str) -> list[str]:
        if folder in ("", "/"):
            return list(self.md_paths)
        prefix = folder.rstrip("/") + "/"
        return [rel for rel in self.md_paths if rel.startswith(prefix)]

    def file_path(self, rel: str) -> Path | None:
        return self._paths.get(rel)

    def resolve(self, linkpath: str, origin: str) -> str | None:
        """The vault path a link points to, like Obsidian's ``getFirstLinkpathDest``."""
        key = (linkpath, get_parent_folder(origin) if origin and linkpath.strip() else origin)
        if key in self._resolve_cache:
            return self._resolve_cache[key]
        result = self._resolve(linkpath, origin)
        self._resolve_cache[key] = result
        return result

    def _resolve(self, linkpath: str, origin: str) -> str | None:
        target = linkpath.strip()
        if not target:
            return origin if origin in self._paths else None
        target = target.removeprefix("/")
        for candidate in (target, target + ".md"):
            exact = self._lower.get(candidate.lower())
            if exact is not None:
                return exact
        folder = self.root / get_parent_folder(origin) if origin else self.root
        if target.startswith(("./", "../")):
            rel = (folder / target).resolve()
            for candidate in (rel, rel.with_name(rel.name + ".md")):
                try:
                    as_rel = candidate.relative_to(self.root).as_posix()
                except ValueError:
                    continue
                if as_rel in self._paths:
                    return as_rel
        found = None
        if "/" in target:
            found = self.vault.find_markdown_by_path(target, folder)
        if found is None:
            name = target.rsplit("/", 1)[-1]
            stem = name[:-3] if name.lower().endswith(".md") else name
            found = self.vault.find_closest_markdown(stem, folder)
            if found is None and "." in name:
                found = self.vault.find_closest(name, folder)
        if found is None:
            return None
        try:
            return self.vault.resolved(found).relative_to(self.root).as_posix()
        except ValueError:
            return None

    def normalize(self, linkpath: str, origin: str) -> str:
        return self.resolve(linkpath, origin) or linkpath

    def resolve_relative(self, path: str, origin: str | None) -> str:
        if not origin:
            return path
        if path.startswith("/"):
            return path[1:]
        relative = get_parent_folder(origin) + "/" + path
        return relative if relative in self._paths else path

    # -- CSV -----------------------------------------------------------------

    def csv(self, path: str) -> list[dict] | None:
        if path in self.csv_cache:
            return self.csv_cache[path]
        file = self._paths.get(path)
        if file is None:
            return None
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        rows = parse_csv(text)
        self.csv_cache[path] = rows
        return rows


def _path_order(rel: str) -> tuple:
    """Folder by folder, case-insensitive, as a walk of the vault tree lists the files."""
    return tuple(part.lower() for part in rel.split("/"))


def _read_starred(root: Path) -> set[str]:
    file = root / ".obsidian" / "bookmarks.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    starred: set[str] = set()

    def walk(items: list) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "file" and isinstance(item.get("path"), str):
                starred.add(item["path"])
            if item.get("type") == "group":
                walk(item.get("items") or [])

    walk(data.get("items") or [] if isinstance(data, dict) else [])
    return starred


def _read_settings(root: Path) -> dict | None:
    file = root / ".obsidian" / "plugins" / "dataview" / "data.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _csv_value(text: str) -> Any:
    """Papa Parse's dynamic typing: numbers, booleans and empty cells."""
    if text == "":
        return None
    if text in ("true", "TRUE", "True"):
        return True
    if text in ("false", "FALSE", "False"):
        return False
    if re.fullmatch(r"\s*-?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?\s*", text, re.IGNORECASE):
        value = float(text)
        return (
            int(value)
            if value.is_integer() and "." not in text and "e" not in text.lower()
            else value
        )
    return text


def parse_csv(text: str) -> list[dict]:
    """A CSV file as Dataview rows: header keys (and their normalised forms), typed values."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    rows = []
    for raw in reader:
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue
        result: dict[str, Any] = {}
        for key, value in raw.items():
            if key is None:
                continue
            parsed = parse_frontmatter_value(_csv_value(value if isinstance(value, str) else ""))
            result[key] = parsed
            result[canonicalize_var_name(key)] = parsed
        rows.append(result)
    return rows
