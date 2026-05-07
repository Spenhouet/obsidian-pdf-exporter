"""Meta Bind plugin implementation.

INPUT and BUTTON widgets are stripped — they are interactive and have no
PDF counterpart. VIEW expressions are evaluated as best-effort string
concatenation of frontmatter fields, with optional ``date(...)`` /
``datetime(...)`` formatting using a small subset of moment.js tokens.
"""

from __future__ import annotations

import datetime
import re

from obsidian_pdf_exporter.plugins.base import ObsidianPlugin
from obsidian_pdf_exporter.plugins.base import PluginContext

_RE_VIEW = re.compile(r"`VIEW\[([^\]`]+)\]\[([^\]`]*)\]`|VIEW\[([^\]]+)\]\[([^\]]*)\]")
_RE_INPUT = re.compile(r"`INPUT\[[^\]`]*(?:\[[^\]`]*\])?\]`|INPUT\[[^\]]*(?:\[[^\]]*\])?\]")
_RE_BUTTON = re.compile(r"`BUTTON\[[^\]`]*\]`|BUTTON\[[^\]]*\]")


class MetaBindPlugin(ObsidianPlugin):
    """Resolve Meta Bind ``VIEW`` widgets; strip ``INPUT`` and ``BUTTON``."""

    name = "meta_bind"
    description = "Resolve Meta Bind VIEW widgets against frontmatter; strip INPUT/BUTTON"
    # Run after Dataview so any tables it generated are already in the
    # markdown by the time we resolve VIEW expressions.
    priority = 20

    def process_markdown(self, content: str, context: PluginContext) -> str:
        fm = context.frontmatter
        content = _RE_VIEW.sub(lambda m: _render_view(m, fm), content)
        content = _RE_INPUT.sub("", content)
        return _RE_BUTTON.sub("", content)


def _render_view(m: re.Match, fm: dict) -> str:
    expr = m.group(1) or m.group(3)
    render_type = (m.group(2) or m.group(4) or "text").lower().strip()
    value = _eval_expr(expr, fm)
    if not value:
        return ""

    if render_type.startswith(("date(", "datetime(")):
        fmt_m = re.match(r"(?:date|datetime)\(([^)]+)\)", render_type)
        if fmt_m:
            try:
                d = datetime.date.fromisoformat(value[:10])
                return d.strftime(_moment_to_strftime(fmt_m.group(1)))
            except ValueError:
                pass

    # Escape bare pipe characters that would break pandoc table cell parsing,
    # but leave pipes inside [[wiki|alias]] spans intact.
    return re.sub(
        r"(\[\[[^\]]*\]\])|(\|)",
        lambda mo: mo.group(1) or r"\|",
        value,
    )


def _eval_expr(expr: str, fm: dict) -> str:
    """Evaluate ``{key}`` references and ``+`` concatenation in a Meta Bind expression."""

    def sub_key(m: re.Match) -> str:
        key = m.group(1).strip()
        val = fm.get(key)
        if val is None:
            return ""
        if isinstance(val, list):
            return ", ".join(str(v) for v in val)
        return str(val)

    result = re.sub(r"\{([^}]+)\}", sub_key, expr)

    if "+" in result:
        parts = result.split("+")
        return "".join(p.strip().strip('"').strip("'") for p in parts)
    return result.strip().strip('"').strip("'")


def _moment_to_strftime(fmt: str) -> str:
    """Translate moment.js date tokens into Python ``strftime`` directives."""
    for moment_tok, py_tok in (
        ("YYYY", "%Y"),
        ("YY", "%y"),
        ("MM", "%m"),
        ("DD", "%d"),
        ("HH", "%H"),
        ("mm", "%M"),
        ("ss", "%S"),
    ):
        fmt = fmt.replace(moment_tok, py_tok)
    return fmt
