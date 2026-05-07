"""Convert Obsidian callout blocks (``> [!note]``) into pandoc fenced divs."""

from __future__ import annotations

import re

_CALLOUT_TYPES: dict[str, tuple[str, str]] = {
    "note": ("note", "Note"),
    "info": ("info", "Info"),
    "tip": ("tip", "Tip"),
    "warning": ("warning", "Warning"),
    "caution": ("warning", "Caution"),
    "danger": ("danger", "Danger"),
    "important": ("important", "Important"),
    "example": ("example", "Example"),
    "abstract": ("abstract", "Abstract"),
    "todo": ("todo", "TODO"),
    "success": ("success", "Success"),
    "check": ("success", "Check"),
    "done": ("success", "Done"),
    "question": ("question", "Question"),
    "help": ("question", "Help"),
    "failure": ("danger", "Failure"),
    "bug": ("danger", "Bug"),
    "quote": ("quote", "Quote"),
}


_BLOCK_PATTERN = re.compile(
    r"^(> \[!\w+\][^\n]*\n(?:>[ \t][^\n]*\n?)*)",
    re.MULTILINE,
)
_BR_PATTERN = re.compile(
    r"> \[!(\w+)\]([^<\n]*?)<br\s*/?>((?:\s*> [^<\n]*(?:<br\s*/?>\s*)?)*)",
    re.MULTILINE | re.IGNORECASE,
)
_INLINE_PATTERN = re.compile(r"> \[!(\w+)\][ \t]+([^\n<]+)", re.MULTILINE)


def convert_callouts(content: str) -> str:
    """Replace Obsidian callouts (block, ``<br>`` and inline) with stable HTML/divs."""
    content = _BLOCK_PATTERN.sub(_replace_block, content)
    content = _BR_PATTERN.sub(_replace_br, content)
    return _INLINE_PATTERN.sub(_replace_inline, content)


def _replace_block(m: re.Match) -> str:
    block = m.group(1)
    lines = block.split("\n")

    first_line = lines[0].lstrip("> ").strip()
    type_match = re.match(r"\[!(\w+)\](.*)", first_line)
    if not type_match:
        return m.group(0)

    raw_type = type_match.group(1).lower()
    custom_title = type_match.group(2).strip()
    css_class, default_title = _CALLOUT_TYPES.get(raw_type, ("note", raw_type.capitalize()))
    title = custom_title or default_title

    body_lines = []
    for line in lines[1:]:
        if line.startswith("> "):
            body_lines.append(line[2:])
        elif line.startswith(">"):
            body_lines.append(line[1:])
        elif line.strip() == "":
            body_lines.append("")
        else:
            break

    body = "\n".join(body_lines).strip()
    return f"\n::: {{.callout .callout-{css_class}}}\n**{title}**\n\n{body}\n:::\n"


def _replace_br(m: re.Match) -> str:
    raw_type = m.group(1).lower()
    custom_title = (m.group(2) or "").strip()
    body_raw = m.group(3) or ""
    css_class, default_title = _CALLOUT_TYPES.get(raw_type, ("note", raw_type.capitalize()))
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
    return (
        f'<span class="callout callout-{css_class}" style="display:block;">'
        f"<strong>{title}:</strong> {body}</span>"
    )


def _replace_inline(m: re.Match) -> str:
    raw_type = m.group(1).lower()
    text = m.group(2).strip()
    css_class, default_title = _CALLOUT_TYPES.get(raw_type, ("note", raw_type.capitalize()))
    return (
        f'<span class="callout callout-{css_class}" style="display:block;">'
        f"<strong>{default_title}:</strong> {text}</span>"
    )
