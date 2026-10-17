"""Show stray HTML tags that would hide the rest of the document as text.

Pandoc passes raw HTML through to the HTML it writes. Some HTML elements hold
raw text, or are never drawn: ``<style>``, ``<script>``, ``<title>``,
``<textarea>``, ``<iframe>``, ``<noscript>``, ``<xmp>``, ``<noembed>``,
``<noframes>``, ``<template>``, ``<select>`` and ``<plaintext>``. When such an
opening tag has no closing tag, the HTML parser of WeasyPrint reads everything
after it, up to the end of the document, as the content of that element. A
sentence like "Anything inside <style> is printed as text" then hides every
following section from the PDF.

Obsidian renders a note block by block, so a stray tag there never hides more
than its own block. This module goes further and keeps all text: an opening
tag of one of these elements without a matching closing tag is written as
``&lt;tag>``, so the PDF shows it as text, as it was typed.

A tag counts as closed when the closing tag follows

- in the same paragraph, for a tag inside a line of text (pandoc reads such
  a tag as inline HTML, which ends with the paragraph), or
- anywhere later in the note, for a tag at the start of a line (pandoc reads
  such a tag as an HTML block, which runs to its closing tag).

``<plaintext>`` has no closing tag in HTML, so it is always shown as text.
Tags inside code (fenced or indented code blocks, inline code) are left alone.
Unclosed ``<!--`` comments need nothing: pandoc already writes them as text.
"""

from __future__ import annotations

import re

from obsidian_pdf_exporter.core.code import outside_code

#: Elements whose content is raw text or not drawn, so an unclosed opening
#: tag hides the rest of the document.
SWALLOWING_TAGS: tuple[str, ...] = (
    "style",
    "script",
    "title",
    "textarea",
    "iframe",
    "noscript",
    "xmp",
    "noembed",
    "noframes",
    "template",
    "select",
    "plaintext",
)

_RE_OPEN = re.compile(
    r"<(?P<tag>" + "|".join(SWALLOWING_TAGS) + r")(?=[\s/>])[^<>]*>",
    re.IGNORECASE,
)

#: What may come before a tag that starts an HTML block: indentation,
#: blockquote markers and list markers.
_RE_BLOCK_PREFIX = re.compile(r"[ \t]*(?:(?:>|[-*+]|\d{1,9}[.)])[ \t]*)*")

#: A line that ends a paragraph: empty, or only blockquote markers.
_RE_BLANK = re.compile(r"[ \t]*(?:>[ \t]*)*$")

_RE_LIST_ITEM = re.compile(r"[ \t]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")

#: Columns of indentation that make a line after a blank line a code block.
_CODE_INDENT = 4


def _indent(line: str) -> int:
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip(" "))


def _indented_code(text: str) -> list[tuple[int, int]]:
    """Return the character ranges of indented code blocks in ``text``.

    A line indented by four or more columns after a blank line is code,
    unless it continues a list item.
    """
    ranges: list[tuple[int, int]] = []
    pos = 0
    prev_blank = True
    in_code = False
    in_list = False
    for line in text.split("\n"):
        end = pos + len(line)
        blank = _RE_BLANK.fullmatch(line) is not None and ">" not in line
        if blank:
            prev_blank = True
        else:
            if _RE_LIST_ITEM.match(line):
                in_list = True
            elif _indent(line) == 0 and prev_blank:
                in_list = False
            in_code = _indent(line) >= _CODE_INDENT and not in_list and (prev_blank or in_code)
            if in_code:
                ranges.append((pos, end))
            prev_blank = False
        pos = end + 1
    return ranges


def _paragraph_end(text: str, start: int) -> int:
    """Return the index where the paragraph holding ``start`` ends."""
    pos = text.find("\n", start)
    while pos != -1:
        nxt = text.find("\n", pos + 1)
        line = text[pos + 1 : nxt if nxt != -1 else len(text)]
        if _RE_BLANK.fullmatch(line):
            return pos
        pos = nxt
    return len(text)


def _neutralize(text: str, found: list[str]) -> str:
    code = _indented_code(text)

    def in_code(index: int) -> bool:
        return any(a <= index < b for a, b in code)

    out: list[str] = []
    pos = 0
    while True:
        m = _RE_OPEN.search(text, pos)
        if m is None:
            break
        if in_code(m.start()):
            out.append(text[pos : m.end()])
            pos = m.end()
            continue
        tag = m.group("tag").lower()
        close_end = -1
        if tag != "plaintext":
            line_start = text.rfind("\n", 0, m.start()) + 1
            block = _RE_BLOCK_PREFIX.fullmatch(text, line_start, m.start()) is not None
            limit = len(text) if block else _paragraph_end(text, m.end())
            close = re.compile(rf"</{tag}\s*>", re.IGNORECASE).search(text, m.end(), limit)
            if close is not None:
                close_end = close.end()
        if close_end >= 0:
            # The element is closed. Its content is raw text, so a tag inside
            # it is no tag: go on after the closing tag.
            out.append(text[pos:close_end])
            pos = close_end
            continue
        found.append(tag)
        out.append(text[pos : m.start()] + "&lt;" + m.group(0)[1:])
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def neutralize_unclosed_tags(content: str) -> tuple[str, list[str]]:
    """Write unclosed opening tags of :data:`SWALLOWING_TAGS` as text.

    Returns the new content and the names of the tags that were changed, in
    the order they appear.
    """
    if _RE_OPEN.search(content) is None:
        return content, []
    found: list[str] = []
    return outside_code(content, lambda text: _neutralize(text, found)), found
