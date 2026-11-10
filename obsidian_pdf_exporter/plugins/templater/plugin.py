"""Templater plugin implementation.

Every Templater tag is removed: ``<% ... %>`` (interpolation), ``<%* ... %>``
(JavaScript execution) and ``<%+ ... %>`` (dynamic command), on one line or
on several. The whitespace control of a tag is applied as Templater does it:
``-`` next to ``<%`` or ``%>`` removes one newline on that side of the tag,
``_`` removes all spaces, tabs and newlines on that side.

Tags inside fenced code blocks and inline code are left as written. Code
spans are only recognized outside of tags, so backticks in the JavaScript of
a tag do not hide the end of the tag.

Templates often start with an execution tag in front of the frontmatter,
which Templater removes when the template is applied. The frontmatter step
does not see such frontmatter, since it is not at the start of the note.
When the note starts with tags and the frontmatter follows them, this plugin
reads the frontmatter into the page context and removes it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.code import RE_CODE_SPAN
from obsidian_pdf_exporter.core.code import outside_code
from obsidian_pdf_exporter.core.frontmatter import RE_FRONTMATTER
from obsidian_pdf_exporter.core.frontmatter import parse_frontmatter
from obsidian_pdf_exporter.core.frontmatter import strip_frontmatter
from obsidian_pdf_exporter.plugins.base import ObsidianPlugin

if TYPE_CHECKING:
    from obsidian_pdf_exporter.plugins.base import PluginContext

#: An inline code span or a Templater tag, whichever starts first. The code
#: span comes first so it keeps group 1, which its closing run refers to.
_RE_TOKEN = re.compile(
    RE_CODE_SPAN.pattern + r"|(?P<tag><%(?P<left>[-_]?)[*+]?[-_]?(?s:.*?)(?P<right>[-_]?)%>)"
)
_RE_ONE_NEWLINE_BEFORE = re.compile(r"(?:\r\n|\n|\r)\Z")
_RE_ONE_NEWLINE_AFTER = re.compile(r"\A(?:\r\n|\n|\r)")


class TemplaterPlugin(ObsidianPlugin):
    """Remove Templater tags and read the frontmatter that follows them."""

    name = "templater"
    description = "Remove Templater tags, read the frontmatter after a leading tag"
    # Run first, so the other plugins see the note without tags and with
    # the frontmatter that was hidden behind a leading tag.
    priority = 1

    def process_markdown(self, content: str, context: PluginContext) -> str:
        if "<%" not in content:
            return content
        starts_with_tag = content.lstrip().startswith("<%")
        content = outside_code(content, strip_tags, inline=False)
        if starts_with_tag and not context.frontmatter and RE_FRONTMATTER.match(content):
            context.frontmatter = parse_frontmatter(content)
            content = strip_frontmatter(content)
        return content


def strip_tags(text: str) -> str:
    """Remove the Templater tags of ``text`` outside inline code spans."""
    out = ""
    pos = 0
    right = ""
    for m in _RE_TOKEN.finditer(text):
        out += _trim(text[pos : m.start()], right, start=True)
        pos = m.end()
        if m.group("tag") is None:
            out += m.group(0)
            right = ""
        else:
            out = _trim(out, m.group("left"), start=False)
            right = m.group("right")
    return out + _trim(text[pos:], right, start=True)


def _trim(text: str, control: str, *, start: bool) -> str:
    """Apply the whitespace control ``-`` or ``_`` to the start or end of ``text``."""
    if control == "-":
        return (_RE_ONE_NEWLINE_AFTER if start else _RE_ONE_NEWLINE_BEFORE).sub("", text)
    if control == "_":
        return text.lstrip() if start else text.rstrip()
    return text
