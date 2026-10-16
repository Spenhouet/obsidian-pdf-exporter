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


def normalize_heading_levels(content: str, base: int) -> str:
    """Re-level the page's headings so they nest under ``base`` without gaps.

    The outermost headings of the page get level ``base``. A heading that
    skips levels (``###`` right after ``#``) moves up to the next free level,
    so section numbers never contain a zero (``1.0.1``). Levels are capped at 6.
    """
    lines = content.split("\n")
    stack: list[int] = []
    in_code_block = False
    for i, line in enumerate(lines):
        if line.startswith(("```", "~~~")):
            in_code_block = not in_code_block
        if in_code_block:
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if not m:
            continue
        level = len(m.group(1))
        while stack and stack[-1] >= level:
            stack.pop()
        new_level = min(base + len(stack), 6)
        stack.append(level)
        lines[i] = "#" * new_level + " " + m.group(2)
    return "\n".join(lines)
