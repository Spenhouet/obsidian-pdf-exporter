"""Links to headings on the same page: ``[[#Heading]]`` and ``[[#Heading|alias]]``.

Pandoc derives heading ids from the heading text and adds ``-1``, ``-2`` ...
when the same text occurs more than once. When several pages are merged into
one document, two pages can share a heading name, so a plain slug can point to
the wrong page. The link is therefore resolved in two steps:

1. :func:`mark_same_page_links` turns the wiki link into a pandoc link that
   records the page (``data-scope``) it was written on.
2. :func:`resolve_heading_links` looks up the real heading id in the HTML,
   preferring headings that belong to that page.
"""

from __future__ import annotations

import html as html_lib
import re

from obsidian_pdf_exporter.core.util import slugify

_FENCE = re.compile(r"^\s*(```|~~~)")
_LINK_OR_CODE = re.compile(r"(`[^`\n]*`)|(?<!!)\[\[#([^\]|^][^\]|]*)(?:\|([^\]]*))?\]\]")
_HEADING = re.compile(r"<h([1-6])\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</h\1>", re.DOTALL)
_HEADING_LINK = re.compile(r"<a\b[^>]*\bclass=\"heading-link\"[^>]*>")
_NUMBER_SPAN = re.compile(r"<span class=\"header-section-number\">.*?</span>", re.DOTALL)


def mark_same_page_links(content: str, scope: str) -> str:
    """Convert ``[[#Heading]]`` links into pandoc links tagged with ``scope``.

    ``scope`` is the anchor of the page heading the content is placed under
    (empty for the export root). Links inside code are left alone.
    """

    def replace(m: re.Match) -> str:
        if m.group(1):
            return m.group(1)
        target = m.group(2).strip()
        heading = target.rsplit("#", 1)[-1].strip()
        label = (m.group(3) or "").strip() or heading
        return f'[{label}](#{slugify(heading)}){{.heading-link data-scope="{scope}"}}'

    out: list[str] = []
    in_fence = False
    for line in content.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        out.append(line if in_fence else _LINK_OR_CODE.sub(replace, line))
    return "\n".join(out)


def resolve_heading_links(html: str) -> str:
    """Point every ``a.heading-link`` at the matching heading id.

    Headings are grouped by the page heading that precedes them. The page
    headings are the ids the links name in ``data-scope``. A page without
    such links is counted to the page before it, which is harmless because
    a page's own headings always come first. A link first looks for its
    heading inside its own page and then anywhere in the document. Unknown
    headings keep their slug.
    """
    page_anchors = set(re.findall(r'class="heading-link" data-scope="([^"]+)"', html))
    scoped: dict[tuple[str, str], str] = {}
    anywhere: dict[str, str] = {}
    scope = ""
    for m in _HEADING.finditer(html):
        heading_id = m.group(2)
        if heading_id in page_anchors:
            scope = heading_id
        text = html_lib.unescape(re.sub(r"<[^>]+>", "", _NUMBER_SPAN.sub("", m.group(3))))
        slug = slugify(text)
        scoped.setdefault((scope, slug), heading_id)
        anywhere.setdefault(slug, heading_id)

    def replace(m: re.Match) -> str:
        tag = m.group(0)
        href = re.search(r'href="#([^"]*)"', tag)
        link_scope = re.search(r'data-scope(?:="([^"]*)")?', tag)
        if not href:
            return tag
        slug = href.group(1)
        key = ((link_scope.group(1) or "") if link_scope else "", slug)
        target = scoped.get(key) or anywhere.get(slug)
        if not target:
            return tag
        return tag.replace(href.group(0), f'href="#{target}"', 1)

    return _HEADING_LINK.sub(replace, html)
