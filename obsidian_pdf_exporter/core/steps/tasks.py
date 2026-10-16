"""Task lists: ``- [ ]`` and ``- [x]``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.html_postprocess import render_task_checkboxes
from obsidian_pdf_exporter.core.steps.base import Step

if TYPE_CHECKING:
    from obsidian_pdf_exporter.core.steps.base import DocumentContext


class TasksStep(Step):
    """Draw task checkboxes as glyphs that stay on the line of the task."""

    name = "tasks"
    description = "Render task list checkboxes"
    priority = 160
    html_priority = 60

    def process_html(self, html: str, context: DocumentContext) -> str:
        return render_task_checkboxes(html)
