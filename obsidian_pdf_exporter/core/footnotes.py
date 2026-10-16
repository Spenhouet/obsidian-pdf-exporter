r"""Footnotes: ``text[^1]`` with ``[^1]: note`` and inline ``^[note]``.

Two things happen here.

Labels are scoped. Obsidian keeps the footnotes of each note apart, but the
export joins all pages into one document, and pandoc uses the last
definition of a label for every reference to it. :func:`scope_labels` gives
the labels of each page (and of each embedded note) a prefix of their own.

Notes go to the bottom of the page. Pandoc writes all notes at the end of
the document. :func:`notes_to_page_bottom` moves each note back to its
reference as ``<span class="footnote">``. The base CSS floats it to the
bottom of the page (CSS GCPM ``float: footnote``, which WeasyPrint supports).
The number pandoc gave the note is kept in ``data-footnote-number``, so the
numbers run through the whole document. When pandoc writes the same note
twice (two references to one label), each reference keeps its own copy.

A note with block content other than paragraphs, like a list or a table,
can not be written inline, so it stays at the end of the document with its
number.
"""

from __future__ import annotations

import re

from obsidian_pdf_exporter.core.code import outside_code

#: Values of ``-O footnotes=...``.
FOOTNOTE_MODES = ("page", "end")

# A label in a reference ``[^x]`` or a definition ``[^x]:``.
_RE_LABEL = re.compile(r"\[\^([^\]\s]+)\]")
# A definition ``[^x]:`` at the start of a line, also inside quotes and callouts.
_RE_DEFINITION = re.compile(r"^[ \t]*(?:>[ \t]*)*\[\^([^\]\s]+)\]:", re.MULTILINE)

_RE_SECTION = re.compile(
    r"<section\b[^>]*\bclass=\"[^\"]*\bfootnotes\b[^\"]*\"[^>]*>(?P<body>.*?)</section>\s*",
    re.DOTALL,
)
_RE_ITEM_START = re.compile(r"<li\b[^>]*\bid=\"(?P<id>fn\d+)\"[^>]*>")
_RE_BACKLINK = re.compile(r"\s*<a\b[^>]*\bclass=\"footnote-back\"[^>]*>.*?</a>", re.DOTALL)
_RE_REF = re.compile(
    r"<a\b(?=[^>]*\bclass=\"footnote-ref\")[^>]*\bhref=\"#(?P<id>fn\d+)\"[^>]*>"
    r"(?:<sup>)?(?P<num>[^<]*)(?:</sup>)?</a>"
)
_RE_PARAGRAPH = re.compile(r"<p\b[^>]*>(.*?)</p>", re.DOTALL)
_RE_BLOCK_TAG = re.compile(
    r"<(?:div|ul|ol|li|table|pre|blockquote|figure|h[1-6]|hr|dl|section|p)\b", re.IGNORECASE
)


def scope_labels(content: str, scope: str) -> str:
    """Prefix every defined footnote label in ``content`` with ``scope``.

    Only labels with a definition ``[^label]:`` are changed. Pandoc shows a
    reference without a definition as written, so it stays as it is. Code
    blocks and inline code stay as written too.
    """
    defined: set[str] = set()

    def collect(text: str) -> str:
        defined.update(_RE_DEFINITION.findall(text))
        return text

    outside_code(content, collect)
    if not defined:
        return content

    def scope_one(m: re.Match) -> str:
        label = m.group(1)
        return f"[^{scope}-{label}]" if label in defined else m.group(0)

    return outside_code(content, lambda text: _RE_LABEL.sub(scope_one, text))


def notes_to_page_bottom(html: str) -> str:
    """Move pandoc's end notes to their references as page footnotes."""
    sections = list(_RE_SECTION.finditer(html))
    if not sections:
        return html
    section = sections[-1]
    ol = re.search(r"<ol\b[^>]*>(.*)</ol>", section.group("body"), re.DOTALL)
    if ol is None:
        return html
    starts = list(_RE_ITEM_START.finditer(ol.group(1)))
    notes: dict[str, str] = {}
    kept: list[tuple[str, str]] = []
    for i, start in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(ol.group(1))
        item = ol.group(1)[start.end() : end].strip()
        item = item.removesuffix("</li>").strip()
        inline = _inline_note(_RE_BACKLINK.sub("", item))
        if inline is None:
            kept.append((start.group("id"), item))
        else:
            notes[start.group("id")] = inline
    if not notes:
        return html

    def replace(m: re.Match) -> str:
        note_id = m.group("id")
        if note_id not in notes:
            return m.group(0)
        number = m.group("num").strip()
        return (
            f'<span class="footnote" id="{note_id}" data-footnote-number="{number}">'
            f"{notes[note_id]}</span>"
        )

    body = html[: section.start()]
    rest = html[section.end() :]
    if kept:
        items = "\n".join(
            f'<li id="{note_id}" value="{note_id[2:]}">{item}</li>' for note_id, item in kept
        )
        new_ol = f"<ol>\n{items}\n</ol>"
        sec_html = section.group(0)
        rest = sec_html.replace(ol.group(0), new_ol, 1) + rest
    return _RE_REF.sub(replace, body) + rest


def _inline_note(item: str) -> str | None:
    """Turn the HTML of one note into inline HTML, or None if it has other blocks."""
    paragraphs = _RE_PARAGRAPH.findall(item)
    rest = _RE_PARAGRAPH.sub("", item).strip()
    if rest and not paragraphs:
        paragraphs, rest = [rest], ""
    if rest or any(_RE_BLOCK_TAG.search(p) for p in paragraphs):
        return None
    if not paragraphs:
        return ""
    first, *others = (p.strip() for p in paragraphs)
    return first + "".join(f'<span class="footnote-paragraph">{p}</span>' for p in others)
