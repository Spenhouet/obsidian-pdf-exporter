"""Heading transforms: offset, strip-by-name."""

from __future__ import annotations

import re

RE_HEADING_LINE = re.compile(r"^(#{1,6})\s+(.+?)(?:\s*\{[^}]*\})?\s*$")


def strip_title_heading(content: str, node_name: str) -> str:
    """Drop the first heading if it matches ``node_name`` (already added by the assembler)."""
    lines = content.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        m = re.match(r"^#{1,6}\s+(.+?)(?:\s*\{[^}]*\})?\s*$", lines[i].strip())
        if m and m.group(1).strip().lower() == node_name.lower():
            remaining = lines[i + 1 :]
            while remaining and not remaining[0].strip():
                remaining = remaining[1:]
            return "\n".join(remaining)
    return content


def offset_headings(content: str, offset: int) -> str:
    """Shift every Markdown heading level down by ``offset`` (caps at level 6)."""
    if offset == 0:
        return content

    lines = content.split("\n")
    result = []
    in_code_block = False
    for raw in lines:
        line = raw
        if line.startswith(("```", "~~~")):
            in_code_block = not in_code_block
        if not in_code_block:
            m = re.match(r"^(#{1,6})\s+(.+)$", line)
            if m:
                current_level = len(m.group(1))
                new_level = min(current_level + offset, 6)
                line = "#" * new_level + " " + m.group(2)
        result.append(line)
    return "\n".join(result)
