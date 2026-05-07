"""Template that styles the inserted/deleted markup produced by the redline pipeline."""

from __future__ import annotations

from importlib import resources

from obsidian_pdf_exporter.templates.base import Decorations
from obsidian_pdf_exporter.templates.base import ExportContext
from obsidian_pdf_exporter.templates.base import Template


class RedlineTemplate(Template):
    """Diff-aware template: same chrome as the default plus ``ins`` / ``del`` styling."""

    name = "redline"
    description = "Tracked-changes styling for redline exports between two git commits"

    def get_css(self) -> str:
        return resources.files(__package__).joinpath("redline.css").read_text(encoding="utf-8")

    def decorations(self, context: ExportContext) -> Decorations | None:
        title_he = _esc_html(_truncate(context.title, 70))
        subtitle_he = _esc_html(context.subtitle) if context.subtitle else ""
        label_css = _css_str(context.label or "")
        date_css = _css_str(context.formatted_date)

        subtitle_span = (
            f'<span class="pdf-header-subtitle">{subtitle_he}</span>' if subtitle_he else ""
        )

        running_html = (
            f'<div class="pdf-running-header">'
            f'<span class="pdf-header-title">{title_he}</span>'
            f"{subtitle_span}"
            f"</div>\n"
        )

        page_css = f"""
.pdf-running-header {{
    position: running(pdf-header);
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    font-family: var(--font-sans, Arial, Helvetica, sans-serif);
}}
.pdf-header-title {{ font-size: 8pt; font-weight: bold; color: #1a1a1a; }}
.pdf-header-subtitle {{ font-size: 7pt; color: #888888; }}

@page {{
    @top-left {{
        content: element(pdf-header);
        vertical-align: bottom;
        padding-bottom: 14pt;
    }}
    @bottom-right {{
        content: "{label_css}\\A Page " counter(page) " / " counter(pages);
        white-space: pre;
        font-family: var(--font-sans, Arial, Helvetica, sans-serif);
        font-size: 7pt;
        color: #606872;
        text-align: right;
        vertical-align: top;
        padding-top: 6pt;
    }}
    @bottom-left {{
        content: "{date_css}";
        font-family: var(--font-sans, Arial, Helvetica, sans-serif);
        font-size: 7pt;
        color: #606872;
        vertical-align: top;
        padding-top: 6pt;
    }}
}}
"""
        return Decorations(running_html=running_html, page_css=page_css)


def _esc_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def _css_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\A ")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
