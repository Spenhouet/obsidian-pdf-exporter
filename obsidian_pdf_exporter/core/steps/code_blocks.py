"""Warn about code blocks of Obsidian plugins that the export does not render.

Obsidian plugins draw some fenced code blocks, for example ```` ```tasks ````
or ```` ```dataviewjs ````. When no step or plugin of the exporter turned
such a block into content, it stays a code block in the PDF. This step
leaves the block as it is and prints a warning, so the gap is not silent.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import PageContext

#: Code block languages that belong to an Obsidian core or community plugin.
PLUGIN_LANGUAGES: frozenset[str] = frozenset(
    {
        "abc",
        "button",
        "chart",
        "datacore",
        "datacorejs",
        "datacorejsx",
        "datacorets",
        "datacoretsx",
        "dataview",
        "dataviewjs",
        "graphviz",
        "kanban",
        "leaflet",
        "markmap",
        "mehrmaid",
        "music-abc",
        "plantuml",
        "query",
        "smiles",
        "tasks",
        "tikz",
        "timeline",
        "todoist",
        "tracker",
        "vega",
        "vega-lite",
    }
)

#: Prefixes of plugin languages, such as ``ad-note`` (Admonition).
PLUGIN_LANGUAGE_PREFIXES: tuple[str, ...] = ("ad-", "meta-bind")

_RE_FENCE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})[ \t]*(?P<lang>[^\s`{]*)")


def plugin_code_blocks(content: str) -> list[str]:
    """Return the language of every fenced code block in ``content`` that belongs to a plugin."""
    found: list[str] = []
    fence = ""
    for line in content.split("\n"):
        m = _RE_FENCE.match(line)
        if fence:
            if m and m.group("fence").startswith(fence) and not m.group("lang"):
                fence = ""
            continue
        if m is None:
            continue
        fence = m.group("fence")
        lang = m.group("lang").lower()
        if lang in PLUGIN_LANGUAGES or lang.startswith(PLUGIN_LANGUAGE_PREFIXES):
            found.append(lang)
    return found


class PluginCodeBlocksStep(Step):
    """Warn about every plugin code block that is still in the page."""

    name = "plugin_code_blocks"
    description = "Warn about plugin code blocks that are not rendered"
    priority = 135

    def process_markdown(self, content: str, context: PageContext) -> str:
        if "```" not in content and "~~~" not in content:
            return content
        for lang in plugin_code_blocks(content):
            context.warn(f"cannot render the {lang} code block in {context.where}, kept as code")
        return content
