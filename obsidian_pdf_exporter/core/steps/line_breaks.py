"""Line breaks: a single newline inside a paragraph, as Obsidian shows it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.steps.base import Step
from obsidian_pdf_exporter.core.util import obsidian_hard_line_breaks

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from obsidian_pdf_exporter.core.steps.base import DocumentContext


def hard_line_breaks(root_folder: Path | None, options: dict[str, str]) -> bool:
    """Decide whether single newlines become line breaks.

    ``-O line_breaks=hard|soft`` wins. Otherwise the vault's "Strict line
    breaks" setting decides, like in Obsidian.
    """
    choice = options.get("line_breaks", "").strip().lower()
    if choice in ("hard", "soft"):
        return choice == "hard"
    if root_folder is None:
        return False
    return obsidian_hard_line_breaks(root_folder)


class LineBreaksStep(Step):
    """Turn on pandoc's ``hard_line_breaks`` unless "Strict line breaks" is set."""

    name = "line_breaks"
    description = "Keep single newlines as line breaks unless strict line breaks is on"
    priority = 150

    def reader_extensions(self, context: DocumentContext) -> Sequence[str]:
        if hard_line_breaks(context.root, context.options):
            return ("hard_line_breaks",)
        return ()
