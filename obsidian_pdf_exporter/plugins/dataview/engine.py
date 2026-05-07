"""DQL evaluator: parses and renders Dataview queries.

Supported subset:

- ``TABLE`` (with optional ``WITHOUT ID``) and ``LIST`` queries
- ``FROM #tag`` and ``FROM "path"`` clauses, with ``AND`` / ``OR`` and ``-``
  negation
- ``WHERE`` expressions: ``field = "x"``, ``field != "x"``, ``NOT``, ``AND``,
  ``OR`` and bare field-truth checks
- ``SORT`` and ``LIMIT``

``TASK``, ``CALENDAR`` and ``dataviewjs`` blocks are replaced with placeholder
text. Unknown queries are left untouched.
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.frontmatter import RE_FRONTMATTER
from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.vault_index import VaultIndex

_DATAVIEW_PAGES_CACHE: dict[int, list[dict]] = {}
_DATAVIEW_FENCE = re.compile(r"```(dataview(?:js)?)\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


def _pages_for(index: VaultIndex) -> list[dict]:
    cached = _DATAVIEW_PAGES_CACHE.get(id(index))
    if cached is not None:
        return cached
    pages: list[dict] = []
    for md_file in index.md_files():
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = parse_frontmatter(content)
        tags = _collect_tags(fm, content)
        pages.append(
            {
                "file": md_file,
                "rel": md_file.relative_to(index.root),
                "name": md_file.stem,
                "tags": tags,
                "fm": fm,
            }
        )
    pages.sort(key=lambda p: str(p["rel"]).lower())
    _DATAVIEW_PAGES_CACHE[id(index)] = pages
    return pages


def _collect_tags(fm: dict, content: str) -> set[str]:
    tags: set[str] = set()
    raw = fm.get("tags", [])
    if isinstance(raw, list):
        for t in raw:
            if isinstance(t, str):
                tags.add(t.lstrip("#").lower())
    elif isinstance(raw, str):
        tags.add(raw.lstrip("#").lower())

    body = RE_FRONTMATTER.sub("", content, count=1)
    # Strip code fences/inline so that "FROM #tag" inside a query isn't picked up
    # as an inline tag itself.
    body = re.sub(r"```[\s\S]*?```", "", body)
    body = re.sub(r"`[^`\n]+`", "", body)
    for m in re.finditer(r"(?<![`\w])#([\w/-]+)", body):
        tags.add(m.group(1).lower())
    return tags


def resolve_dataview_blocks(content: str, vault_index: VaultIndex) -> str:
    """Replace fenced ``dataview`` / ``dataviewjs`` blocks with rendered markdown."""

    def replace(m: re.Match) -> str:
        lang = m.group(1).lower()
        query = m.group(2)
        if lang == "dataviewjs":
            return "*[DataviewJS queries are not supported in PDF export.]*"
        rendered = _execute(query, vault_index)
        return rendered if rendered is not None else m.group(0)

    return _DATAVIEW_FENCE.sub(replace, content)


def _execute(  # noqa: C901, PLR0912 - it's a small parser; splitting hurts readability
    query_text: str,
    vault_index: VaultIndex,
) -> str | None:
    lines = [line.rstrip() for line in query_text.strip().splitlines()]
    if not lines:
        return None
    type_match = re.match(r"^(TABLE|LIST|TASK|CALENDAR)\s*(.*)", lines[0].strip(), re.IGNORECASE)
    if not type_match:
        return None

    query_type = type_match.group(1).upper()
    fields_parts = [type_match.group(2).strip()] if type_match.group(2).strip() else []
    from_str = ""
    where_str = ""
    sort_fields: list[tuple[str, bool]] = []
    limit: int | None = None

    for line in lines[1:]:
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("FROM "):
            from_str = stripped[5:].strip()
        elif upper.startswith("WHERE "):
            where_str = stripped[6:].strip()
        elif upper.startswith("SORT "):
            for raw in stripped[5:].split(","):
                token = raw.strip()
                m = re.match(r"^(.+?)\s+(ASC|DESC)$", token, re.IGNORECASE)
                if m:
                    sort_fields.append((m.group(1).strip(), m.group(2).upper() == "ASC"))
                elif token:
                    sort_fields.append((token, True))
        elif upper.startswith("LIMIT "):
            with contextlib.suppress(ValueError):
                limit = int(stripped[6:].strip())
        elif stripped and not re.match(
            r"^(FROM|WHERE|SORT|LIMIT|GROUP BY)\s", stripped, re.IGNORECASE
        ):
            fields_parts.append(stripped)

    fields_str = " ".join(fields_parts).strip()
    without_id = False
    if query_type == "TABLE" and fields_str.upper().startswith("WITHOUT ID"):
        without_id = True
        fields_str = fields_str[10:].strip()

    fields = _parse_fields(fields_str) if query_type in ("TABLE", "LIST") else []
    conditions = _parse_from(from_str) if from_str else []

    pages = [p for p in _pages_for(vault_index) if _matches_from(p, conditions)]
    if where_str:
        pages = [p for p in pages if _eval_where(p, where_str)]
    if sort_fields:
        pages = _sort_pages(pages, sort_fields)
    if limit is not None:
        pages = pages[:limit]

    if query_type == "TABLE":
        return _render_table(pages, fields, without_id=without_id)
    if query_type == "LIST":
        field_expr = fields[0][0] if fields else ""
        return _render_list(pages, field_expr)
    if query_type == "TASK":
        return "*[Task queries are not supported in PDF export.]*"
    return None


def _parse_from(from_str: str) -> list[tuple[str, str, bool, str]]:
    tokens = re.split(r"\b(AND|OR)\b", from_str.strip(), flags=re.IGNORECASE)
    conditions: list[tuple] = []
    op = "AND"
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        if token.upper() in ("AND", "OR"):
            op = token.upper()
            continue
        negate = token.startswith("-")
        if negate:
            token = token[1:].strip()
        if token.startswith("#"):
            conditions.append(("tag", token[1:].lower(), negate, op))
        elif token.startswith('"') and token.endswith('"'):
            conditions.append(("path", token[1:-1], negate, op))
        op = "AND"
    return conditions


def _matches_from(page: dict, conditions: list[tuple]) -> bool:
    if not conditions:
        return True
    result: bool | None = None
    for kind, value, negate, op in conditions:
        if kind == "tag":
            match = value in page["tags"]
        elif kind == "path":
            rel_fwd = str(page["rel"]).replace("\\", "/")
            prefix = value.rstrip("/")
            match = (
                rel_fwd.lower().startswith(prefix.lower() + "/")
                or rel_fwd.lower() == prefix.lower()
            )
        else:
            match = False
        if negate:
            match = not match
        if result is None:
            result = match
        elif op == "AND":
            result = result and match
        else:
            result = result or match
    return bool(result)


def _parse_fields(fields_str: str) -> list[tuple[str, str]]:
    if not fields_str.strip():
        return []
    fields: list[tuple[str, str]] = []
    for raw in fields_str.split(","):
        part = raw.strip()
        if not part:
            continue
        m = re.match(r'^(.+?)\s+AS\s+"([^"]+)"$', part, re.IGNORECASE)
        if m:
            fields.append((m.group(1).strip(), m.group(2)))
        else:
            fields.append((part, part.replace("_", " ").title()))
    return fields


def _field_value(page: dict, field: str) -> str:
    val = page["fm"].get(field)
    if val is None:
        return ""
    if isinstance(val, list):
        text = ", ".join(str(v) for v in val)
    elif isinstance(val, bool):
        text = "Yes" if val else "No"
    else:
        text = str(val).strip()
    return re.sub(
        r"(\[\[[^\]]*\]\])|(\|)",
        lambda mo: mo.group(1) or r"\|",
        text,
    )


def _sort_pages(pages: list[dict], sort_fields: list[tuple[str, bool]]) -> list[dict]:
    result = list(pages)
    for field, ascending in reversed(sort_fields):

        def key_fn(p: dict, f: str = field) -> str:
            if f.lower() in ("null", ""):
                return p["name"].lower()
            return _field_value(p, f).lower()

        result.sort(key=key_fn, reverse=not ascending)
    return result


def _eval_where(page: dict, expr: str) -> bool:  # noqa: PLR0911 - small predicate evaluator
    expr = expr.strip()
    if expr.upper().startswith("NOT "):
        return not _eval_where(page, expr[4:])
    and_parts = re.split(r"\bAND\b", expr, flags=re.IGNORECASE)
    if len(and_parts) > 1:
        return all(_eval_where(page, p) for p in and_parts)
    or_parts = re.split(r"\bOR\b", expr, flags=re.IGNORECASE)
    if len(or_parts) > 1:
        return any(_eval_where(page, p) for p in or_parts)
    m = re.match(r'^(\w+)\s*!=\s*"([^"]*)"$', expr)
    if m:
        return _field_value(page, m.group(1)) != m.group(2)
    m = re.match(r'^(\w+)\s*=\s*"([^"]*)"$', expr)
    if m:
        return _field_value(page, m.group(1)) == m.group(2)
    m = re.match(r"^(\w+)$", expr)
    if m:
        return bool(_field_value(page, m.group(1)))
    return True


def _render_table(pages: list[dict], fields: list[tuple[str, str]], *, without_id: bool) -> str:
    if not pages:
        return "*No results.*"

    if not fields:
        seen: set[str] = set()
        all_keys: list[str] = []
        for page in pages:
            for k in page["fm"]:
                if k not in seen and k != "tags":
                    seen.add(k)
                    all_keys.append(k)
        fields = [(k, k.replace("_", " ").title()) for k in all_keys] or [("name", "Name")]

    if without_id:
        headers = [label for _, label in fields]
        rows = [[_field_value(p, f) for f, _ in fields] for p in pages]
    else:
        headers = ["File", *(label for _, label in fields)]
        rows = [[p["name"], *(_field_value(p, f) for f, _ in fields)] for p in pages]

    return _format_markdown_table(headers, rows)


def _format_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    col_widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(len(headers))]

    def fmt(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(cells)) + " |"

    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    return "\n".join([fmt(headers), sep, *(fmt(r) for r in rows)])


def _render_list(pages: list[dict], field_expr: str) -> str:
    if not pages:
        return "*No results.*"
    out: list[str] = []
    for page in pages:
        if field_expr.strip():
            val = _field_value(page, field_expr.strip())
            out.append(f"- **{page['name']}**: {val}" if val else f"- {page['name']}")
        else:
            out.append(f"- {page['name']}")
    return "\n".join(out)
