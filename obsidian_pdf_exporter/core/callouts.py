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

# ``> [!type]``, ``> [!type]+``, ``> [!type]- Custom title``
_HEADER = re.compile(r"^ {0,3}>[ \t]?\[!([\w-]+)\][+-]?[ \t]*(.*)$")
_QUOTE_LINE = re.compile(r"^ {0,3}>")
_FENCE = re.compile(r"^\s*(```|~~~)")
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
    converted again, which handles nested callouts (``> > [!note]``).
    """
    lines = content.split("\n")
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            in_fence = not in_fence
        header = None if in_fence else _HEADER.match(line)
        if header is None or "<br" in line.lower():
            out.append(line)
            i += 1
            continue
        j = i + 1
        while j < len(lines) and _QUOTE_LINE.match(lines[j]):
            j += 1
        body = [_unquote(raw) for raw in lines[i + 1 : j]]
        out.append(_render_block(header, body))
        i = j
    return "\n".join(out)


def _unquote(line: str) -> str:
    line = line.lstrip(" ")
    if line.startswith("> "):
        return line[2:]
    return line[1:]


def _render_block(header: re.Match, body: list[str]) -> str:
    raw_type = header.group(1).lower()
    classes, default_title = callout_classes(raw_type)
    title = header.group(2).strip() or default_title
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
