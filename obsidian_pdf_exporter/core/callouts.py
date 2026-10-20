"""Convert Obsidian callout blocks (``> [!note]``) into pandoc fenced divs.

Obsidian treats every ``> [!type]`` blockquote as a callout. Known types map
onto a canonical CSS class (``caution`` is styled like ``warning``). Unknown
types keep their own class and also get ``callout-note``, so they fall back to
the note styling like in Obsidian.
"""

from __future__ import annotations

import re

_CALLOUT_TYPES: dict[str, tuple[str, str]] = {
    "note": ("note", "Note"),
    "info": ("info", "Info"),
    "tip": ("tip", "Tip"),
    "hint": ("tip", "Hint"),
    "warning": ("warning", "Warning"),
    "attention": ("warning", "Attention"),
    "caution": ("warning", "Caution"),
    "danger": ("danger", "Danger"),
    "error": ("danger", "Error"),
    "important": ("important", "Important"),
    "example": ("example", "Example"),
    "abstract": ("abstract", "Abstract"),
    "summary": ("abstract", "Summary"),
    "tldr": ("abstract", "TL;DR"),
    "todo": ("todo", "TODO"),
    "success": ("success", "Success"),
    "check": ("success", "Check"),
    "done": ("success", "Done"),
    "question": ("question", "Question"),
    "help": ("question", "Help"),
    "faq": ("question", "FAQ"),
    "failure": ("danger", "Failure"),
    "fail": ("danger", "Fail"),
    "missing": ("danger", "Missing"),
    "bug": ("danger", "Bug"),
    "quote": ("quote", "Quote"),
    "cite": ("quote", "Cite"),
}

# ``> [!type]``, ``> [!type]+``, ``> [!type]- Custom title``. The lead is the
# indentation and an optional list marker, for a callout inside a list item.
_HEADER = re.compile(
    r"^(?P<lead>(?P<indent>[ \t]*)(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)?)"
    r">[ \t]?\[!(?P<type>[\w-]+)\][+-]?[ \t]*(?P<title>.*)$"
)
# Four spaces of indentation outside a list start an indented code block.
_CODE_INDENT = 4
_LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]+|$)")
_QUOTE_LINE = re.compile(r"^ {0,3}>")
_FENCE = re.compile(r"^\s*(```|~~~)")
_BLOCK_START = re.compile(
    r"^\s{0,3}(?:#{1,6}(?:\s|$)|```|~~~|[-*+](?:\s|$)|1[.)](?:\s|$)|(?:[-*_]\s*){3,}$|<|\|)"
)
_BR_PATTERN = re.compile(
    r"> \[!([\w-]+)\][+-]?([^<\n]*?)<br\s*/?>((?:\s*> [^<\n]*(?:<br\s*/?>\s*)?)*)",
    re.MULTILINE | re.IGNORECASE,
)
_INLINE_PATTERN = re.compile(r"> \[!([\w-]+)\][+-]?[ \t]+([^\n<]+)", re.MULTILINE)


def callout_classes(raw_type: str) -> tuple[str, str]:
    """Return the CSS classes and the default title for a callout type."""
    key = raw_type.lower()
    known = _CALLOUT_TYPES.get(key)
    if known:
        css, title = known
        classes = f"callout callout-{css}"
        if css != key:
            classes += f" callout-{key}"
        return classes, title
    return f"callout callout-{key} callout-note", key.replace("-", " ").capitalize()


def convert_callouts(content: str) -> str:
    """Replace Obsidian callouts (block, ``<br>`` and inline) with stable HTML/divs."""
    content = _convert_blocks(content)
    content = _BR_PATTERN.sub(_replace_br, content)
    return _INLINE_PATTERN.sub(_replace_inline, content)


def _convert_blocks(content: str) -> str:
    """Turn every ``> [!type]`` blockquote into a fenced div.

    The callout runs until the first line that does not start with ``>``, so
    blank ``>`` lines keep the following paragraphs inside it. The body is
    converted again, which handles nested callouts (``> > [!note]``). A
    callout that starts a list item (``- > [!note]``) or is indented to the
    content of one stays inside that list item.

    Indentation follows CommonMark: outside a list, up to three spaces before
    ``>`` still start a callout and four start a code block. Inside a list it
    counts from the content of the item.
    """
    lines = content.split("\n")
    out: list[str] = []
    in_fence = False
    items: list[int] = []  # content columns of the open list items, innermost last
    previous_blank = True
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            in_fence = not in_fence
        if previous_blank and line.strip():
            _close_items(items, _width(line))
        header = None if in_fence or "<br" in line.lower() else _HEADER.match(line)
        place = None if header is None else _place(header, items)
        if header is None or place is None:
            _open_item(items, line)
            previous_blank = not line.strip()
            out.append(line)
            i += 1
            continue
        lead, indent = place
        j = i + 1
        body: list[str] = []
        while j < len(lines):
            rest = lines[j].removeprefix(indent)
            if _QUOTE_LINE.match(rest):
                body.append(_unquote(rest))
            elif _is_lazy_continuation(rest, body[-1] if body else line):
                body.append(rest)
            else:
                break
            j += 1
        out.extend(_in_container(_render_block(header, body), lead, indent))
        if lead.strip():
            _open_item(items, header.group("lead"))
        previous_blank = not lead.strip()
        i = j
    return "\n".join(out)


def _width(text: str) -> int:
    """The column of the first character of ``text`` that is not a space."""
    return len(text.expandtabs(4)) - len(text.expandtabs(4).lstrip())


def _close_items(items: list[int], column: int) -> None:
    """After a blank line, a line left of an item's content ends that item."""
    while items and items[-1] > column:
        items.pop()


def _open_item(items: list[int], line: str) -> None:
    m = _LIST_ITEM.match(line)
    if m is None:
        return
    _close_items(items, _width(line))
    items.append(len(m.group(0).expandtabs(4)))


def _place(header: re.Match, items: list[int]) -> tuple[str, str] | None:
    """Where a callout header goes: the lead to write and the indent of its other lines.

    None when the header is an indented code block.
    """
    column = len(header.group("indent").expandtabs(4))
    lead = header.group("lead").expandtabs(4)
    inside = [c for c in items if c <= column]
    if lead.strip():  # a list marker: the callout starts a list item
        if column - (inside[-1] if inside else 0) >= _CODE_INDENT:
            return None
        return lead, " " * len(lead)
    if inside and column - inside[-1] < _CODE_INDENT:
        return " " * inside[-1], " " * inside[-1]
    if not inside and column < _CODE_INDENT:
        return "", ""
    return None


def _in_container(block: str, lead: str, indent: str) -> list[str]:
    """Place the lines of a rendered callout after ``lead``, indented by ``indent``."""
    if not lead:
        return [block]
    lines = block.strip("\n").split("\n")
    rest = [indent + line if line.strip() else "" for line in lines[1:]]
    if lead.strip():  # a list marker: the callout is the start of the item
        return [lead + lines[0], *rest]
    return ["", indent + lines[0], *rest, ""]


def _is_lazy_continuation(line: str, previous: str) -> bool:
    """True if ``line`` continues the callout's paragraph without a ``>``.

    As in CommonMark, a line right after paragraph text belongs to the quote
    unless it is blank or starts a new block (heading, list, fence, rule).
    """
    if not line.strip() or not previous.strip():
        return False
    return _BLOCK_START.match(line) is None


def _unquote(line: str) -> str:
    line = line.lstrip(" ")
    if line.startswith("> "):
        return line[2:]
    return line[1:]


def _render_block(header: re.Match, body: list[str]) -> str:
    raw_type = header.group("type").lower()
    classes, default_title = callout_classes(raw_type)
    title = header.group("title").strip() or default_title
    attrs = " ".join(f".{c}" for c in classes.split())
    inner = _convert_blocks("\n".join(body)).strip("\n")
    parts = [f'\n::: {{{attrs} data-callout="{raw_type}"}}', f"[**{title}**]{{.callout-title}}"]
    if inner.strip():
        parts.append(f"\n{inner}")
    parts.append(":::\n")
    return "\n".join(parts)


def _replace_br(m: re.Match) -> str:
    custom_title = (m.group(2) or "").strip()
    body_raw = m.group(3) or ""
    classes, default_title = callout_classes(m.group(1))
    title = custom_title or default_title
    body_parts = []
    for raw in re.split(r"<br\s*/?>", body_raw, flags=re.IGNORECASE):
        part = raw.strip()
        if part.startswith("> "):
            body_parts.append(part[2:].strip())
        elif part.startswith(">"):
            body_parts.append(part[1:].strip())
        elif part:
            body_parts.append(part)
    body = " ".join(filter(None, body_parts))
    return f'<span class="{classes}" style="display:block;"><strong>{title}:</strong> {body}</span>'


def _replace_inline(m: re.Match) -> str:
    text = m.group(2).strip()
    classes, default_title = callout_classes(m.group(1))
    return (
        f'<span class="{classes}" style="display:block;">'
        f"<strong>{default_title}:</strong> {text}</span>"
    )
