"""Tests for drawing Mermaid diagrams with Pele in the embedded V8 engine."""

from __future__ import annotations

import re
import shutil
from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core import diagram_fit
from obsidian_pdf_exporter.core import mermaid
from obsidian_pdf_exporter.core import mermaid_pele
from obsidian_pdf_exporter.core.html_postprocess import inline_svg_images
from obsidian_pdf_exporter.core.mermaid import MermaidSettings
from obsidian_pdf_exporter.core.mermaid import mermaid_settings
from obsidian_pdf_exporter.core.mermaid import render_mermaid_blocks
from obsidian_pdf_exporter.core.mermaid_pele import PeleRenderer
from obsidian_pdf_exporter.core.mermaid_pele import PeleTheme
from obsidian_pdf_exporter.core.mermaid_pele import diagram_font_size
from obsidian_pdf_exporter.core.mermaid_pele import finish_svg
from obsidian_pdf_exporter.core.mermaid_pele import pele_theme
from obsidian_pdf_exporter.core.mermaid_pele import resolve_vars
from obsidian_pdf_exporter.core.mermaid_pele import series_colors

if TYPE_CHECKING:
    from pathlib import Path

PELE = MermaidSettings()
FLOWCHART = "flowchart LR\n  A[Collect data] -->|then| B{Valid?}"


def _block(code: str) -> str:
    return f"```mermaid\n{code}\n```"


def _images(markdown: str) -> list[tuple[str, str]]:
    return re.findall(r"!\[\]\((mermaid-[0-9a-f]+\.svg)\)\{([^}]*)\}", markdown)


# ---- Rendering --------------------------------------------------------------


def test_pele_renders_svg(tmp_path: Path) -> None:
    messages: list[str] = []
    out = render_mermaid_blocks(_block(FLOWCHART), tmp_path, PELE, log=messages.append)

    [(name, attrs)] = _images(out)
    assert ".mermaid-flowchart" in attrs
    svg = (tmp_path / name).read_text(encoding="utf-8")
    root = re.search(r"<svg\b[^>]*>", svg)
    assert root
    assert "style=" not in root.group(0)
    assert ' height="' not in root.group(0)
    assert re.search(r' width="[\d.]+"', root.group(0))
    assert 'font-size="16"' in root.group(0)
    assert "var(" not in svg
    assert "color-mix(" not in svg
    assert "currentColor" not in svg
    assert "Collect data" in svg
    assert any("with Pele" in m for m in messages)
    assert not any("Warning" in m for m in messages)


def test_pele_renders_every_diagram_type_once(tmp_path: Path) -> None:
    blocks = [
        FLOWCHART,
        "sequenceDiagram\n  A->>B: Hello",
        'pie title Time\n  "A" : 60\n  "B" : 40',
        "gantt\n  dateFormat YYYY-MM-DD\n  section S\n  Task :2027-01-01, 3d",
        "classDiagram\n  Animal <|-- Dog",
        "stateDiagram-v2\n  [*] --> Draft",
        "erDiagram\n  A ||--o{ B : has",
        "mindmap\n  root((Root))\n    Child",
        "timeline\n  2027 : Start",
        "gitGraph\n  commit\n  branch b\n  commit",
    ]
    md = "\n\n".join(_block(code) for code in [*blocks, blocks[0]])
    out = render_mermaid_blocks(md, tmp_path, PELE)
    assert "```mermaid" not in out
    assert len(_images(out)) == len(blocks) + 1
    assert len(list(tmp_path.glob("mermaid-*.svg"))) == len(blocks)
    for svg in tmp_path.glob("mermaid-*.svg"):
        assert "var(" not in svg.read_text(encoding="utf-8")


def test_pele_output_is_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    render_mermaid_blocks(_block(FLOWCHART), tmp_path, PELE)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    monkeypatch.setattr(mermaid_pele.PeleRenderer, "__init__", fail)
    assert _images(render_mermaid_blocks(_block(FLOWCHART), tmp_path, PELE))


def test_pele_failure_keeps_code(tmp_path: Path) -> None:
    messages: list[str] = []
    bad = _block("flowchart LR\n  A --> ((")
    out = render_mermaid_blocks(bad, tmp_path, PELE, log=messages.append)

    assert out == bad
    assert any(m.startswith("  Warning: Pele could not draw") for m in messages)
    assert any("could not be drawn and stay as code" in m for m in messages)


def test_unknown_diagram_type_stays_code(tmp_path: Path) -> None:
    messages: list[str] = []
    out = render_mermaid_blocks(_block("notADiagram\n  x"), tmp_path, PELE, log=messages.append)
    assert "```mermaid" in out
    assert any("Pele could not draw" in m for m in messages)


def test_closing_br_tag_breaks_the_line() -> None:
    with PeleRenderer(PeleTheme()) as renderer:
        result = renderer.render('flowchart LR\n  A["Local</br>Database"]', {"responsive": False})
    assert "<tspan" in result.svg
    assert "LocalDatabase" not in result.svg


def test_wide_pele_diagram_goes_to_landscape_when_asked(tmp_path: Path) -> None:
    chain = " --> ".join(f"N{i}[Step number {i}]" for i in range(12))
    block = _block(f"flowchart LR\n  {chain}")
    [(_name, attrs)] = _images(render_mermaid_blocks(block, tmp_path, PELE))
    assert ".landscape" not in attrs
    on = mermaid_settings({"mermaid.landscape": "on"})
    [(_name, attrs)] = _images(render_mermaid_blocks(block, tmp_path, on))
    assert ".landscape" in attrs


XY_CHART = 'xychart-beta horizontal\n  x-axis ["A", "B", "C"]\n  bar [3, 5, 2]\n  bar [1, 4, 6]\n'


def _bar_colors(svg: str) -> list[str]:
    return re.findall(r'class="pele-series pele-bars" fill="([^"]+)"', svg)


def test_xychart_uses_plot_color_palette(tmp_path: Path) -> None:
    config = {"themeVariables": {"xyChart": {"plotColorPalette": "#112233, #445566"}}}
    out = render_mermaid_blocks(_block(XY_CHART), tmp_path, MermaidSettings(config=config))
    [(name, _attrs)] = _images(out)
    assert _bar_colors((tmp_path / name).read_text(encoding="utf-8")) == ["#112233", "#445566"]


def test_short_palette_starts_again() -> None:
    colors = series_colors(
        "", "xychart", {"themeVariables": {"xyChart": {"plotColorPalette": "#111"}}}
    )
    assert colors["--pele-series-1"] == colors["--pele-series-3"] == "#111"


def test_palette_from_front_matter_wins() -> None:
    code = "---\nconfig:\n  themeVariables:\n    xyChart:\n      plotColorPalette: '#abcdef'\n---\n"
    config = {"themeVariables": {"xyChart": {"plotColorPalette": "#111111, #222222"}}}
    colors = series_colors(code + XY_CHART, "xychart-beta", config)
    assert colors["--pele-series-1"] == colors["--pele-series-2"] == "#abcdef"


def test_pie_colors() -> None:
    config = {"themeVariables": {"pie1": "#aa0000", "pie3": "#00aa00", "xyChart": {}}}
    assert series_colors("pie\n", "pie", config) == {
        "--pele-series-1": "#aa0000",
        "--pele-series-3": "#00aa00",
    }
    assert series_colors("flowchart LR\n", "flowchart", config) == {}


def test_palette_changes_the_image_name(tmp_path: Path) -> None:
    plain = render_mermaid_blocks(_block(XY_CHART), tmp_path, PELE)
    config = {"themeVariables": {"xyChart": {"plotColorPalette": "#112233"}}}
    colored = render_mermaid_blocks(_block(XY_CHART), tmp_path, MermaidSettings(config=config))
    assert _images(plain)[0][0] != _images(colored)[0][0]


def test_font_size_from_front_matter(tmp_path: Path) -> None:
    code = "---\nconfig:\n  themeVariables:\n    fontSize: 12px\n---\n" + FLOWCHART
    out = render_mermaid_blocks(_block(code), tmp_path, PELE)
    [(name, _attrs)] = _images(out)
    image = tmp_path / name
    assert 'font-size="12"' in image.read_text(encoding="utf-8")
    assert mermaid._font_px(image) == 12


def test_diagram_font_size_order() -> None:
    config = {"themeVariables": {"fontSize": "14px"}}
    front = "---\nconfig:\n  themeVariables:\n    fontSize: 11\n---\nflowchart LR\n  A"
    assert diagram_font_size(FLOWCHART, {}) is None
    assert diagram_font_size(FLOWCHART, config) == 14
    assert diagram_font_size(front, config) == 11
    assert diagram_font_size(FLOWCHART, {"themeVariables": {"fontSize": "huge"}}) is None


# ---- Theme ------------------------------------------------------------------

TEMPLATE_CSS = """
:root { --font-sans: 'Inter', 'Arial', sans-serif; --ink: #222222; --brand: #2c5282; }
body { font-family: var(--font-sans); color: var(--ink); }
code, pre { font-family: 'Courier New', monospace; }
.pele { --pele-accent: var(--brand); --pele-surface: #eef2f7; }
h1 { font-family: serif; color: red; }
"""


def test_theme_follows_the_template_css() -> None:
    theme = pele_theme(TEMPLATE_CSS)
    assert theme.font_family == "'Inter', 'Arial', sans-serif"
    assert theme.font_mono == "'Courier New', monospace"
    assert theme.variables["--pele-fg"] == "#222222"
    assert theme.variables["--pele-accent"] == "#2c5282"
    assert theme.variables["--pele-surface"] == "#eef2f7"


def test_theme_font_family_of_the_mermaid_config_wins() -> None:
    theme = pele_theme(TEMPLATE_CSS, {"themeVariables": {"fontFamily": "Georgia, serif"}})
    assert theme.font_family == "Georgia, serif"


def test_theme_without_css_uses_pele_defaults() -> None:
    theme = pele_theme("")
    assert theme.variables == {}
    assert theme.font_family == "sans-serif"


def test_theme_colors_end_up_in_the_svg(tmp_path: Path) -> None:
    out = render_mermaid_blocks(_block(FLOWCHART), tmp_path, PELE, css=TEMPLATE_CSS)
    [(name, _attrs)] = _images(out)
    svg = (tmp_path / name).read_text(encoding="utf-8")
    assert 'fill="#eef2f7"' in svg
    assert "font-family=\"'Inter', 'Arial', sans-serif\"" in svg
    assert 'color="#222222"' in svg


def test_theme_change_renders_again(tmp_path: Path) -> None:
    first = render_mermaid_blocks(_block(FLOWCHART), tmp_path, PELE)
    second = render_mermaid_blocks(_block(FLOWCHART), tmp_path, PELE, css=TEMPLATE_CSS)
    assert first != second


# ---- SVG clean-up -----------------------------------------------------------


def test_resolve_vars_uses_values_then_fallbacks() -> None:
    values = {"--a": "var(--b)", "--b": "#123"}
    assert resolve_vars("var(--a)", values.get) == "#123"
    assert resolve_vars("var(--x,rgb(1, 2, 3))", values.get) == "rgb(1, 2, 3)"
    assert resolve_vars("var(--x)", values.get) == ""
    assert resolve_vars("1px solid var(--b)", values.get) == "1px solid #123"


def test_resolve_vars_stops_on_cycles() -> None:
    values = {"--a": "var(--a, red)"}
    assert resolve_vars("var(--a)", values.get) == "red"


def test_finish_svg_inlines_variables() -> None:
    svg = (
        '<svg class="pele" viewBox="0 0 10 10" width="10" height="10" '
        'style="--_s:var(--pele-surface,#f3f3f3);--_bg:var(--pele-bg,#fff);'
        "color:var(--pele-fg,#1f1f1f);font:14px sans-serif;"
        'font-family:var(--pele-font,sans-serif)" fill="var(--pele-fg,#1f1f1f)">'
        '<rect fill="var(--_s)" style="rx:var(--pele-radius,4px)"/>'
        '<rect fill="color-mix(in srgb,var(--_s) 50%,var(--_bg))"/>'
        '<path stroke="currentColor"/></svg>'
    )
    theme = PeleTheme(variables={"--pele-surface": "#000000"}, font_family="Arial")
    out = finish_svg(svg, theme)
    assert 'fill="#000000"' in out
    assert 'rx="4px"' in out
    assert 'fill="#808080"' in out
    assert 'stroke="#1f1f1f"' in out
    assert 'font-size="14"' in out
    assert 'font-family="sans-serif"' in out
    assert ' height="' not in out
    assert "var(" not in out


# ---- Text widths ------------------------------------------------------------


def test_pango_measures_text() -> None:
    measurer = mermaid_pele._PangoMeasurer(PeleTheme())
    if not measurer.available():
        pytest.skip("Pango is not available")
    widths = measurer.widths(
        ["0|16|Hello world", "1|16|Hello world", "4|16|Hello world", "0|32|Hello world", "0|16|"]
    )
    assert widths["0|16|Hello world"] > 0
    assert widths["1|16|Hello world"] >= widths["0|16|Hello world"]
    assert widths["4|16|Hello world"] > 0
    assert widths["0|32|Hello world"] == pytest.approx(2 * widths["0|16|Hello world"], rel=0.05)
    assert widths["0|16|"] == 0


def test_labels_are_measured_in_the_diagram_font() -> None:
    """A label box is as wide as Pango measures the label, plus Pele's padding."""
    label = "Collect all data"
    code = f"flowchart LR\n  A[{label}]"
    measurer = mermaid_pele._PangoMeasurer(PeleTheme())
    if not measurer.available():
        pytest.skip("Pango is not available")
    with PeleRenderer(PeleTheme()) as renderer:
        svg = renderer.render(code, {"responsive": False, "padding": 0}).svg
    text_width = measurer.widths([f"0|16|{label}"])[f"0|16|{label}"]
    box = re.search(r'<rect x="[-\d.]+" y="[-\d.]+" width="([\d.]+)"', svg)
    assert box
    padding = float(box.group(1)) - text_width
    assert 0 < padding < 60


def test_characters_without_font_are_shown_as_one_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    measurer = mermaid_pele._PangoMeasurer(PeleTheme())
    monkeypatch.setattr(measurer, "covered", lambda c: c not in "नम")
    assert measurer.missing("नमस्ते नम") == "नम"
    assert measurer.shown("aनमb") == "a\u25a1\u25a1b"
    monkeypatch.setattr(measurer, "covered", lambda c: c not in "नम\u25a1")
    assert measurer.shown("नa") == "\ufffda"


# ---- Layout -----------------------------------------------------------------


def test_tall_pele_diagram_is_cut_into_parts(tmp_path: Path) -> None:
    weasyprint = pytest.importorskip("weasyprint")
    steps = "\n".join(f"  A->>B: Request {i}\n  B-->>A: Response {i}" for i in range(40))
    out = render_mermaid_blocks(_block(f"sequenceDiagram\n{steps}"), tmp_path, PELE)
    [(name, _attrs)] = _images(out)
    body = inline_svg_images(f'<img class="doc-image mermaid" src="{name}">', tmp_path)
    page = "@page { size: 600px 800px; margin: 50px } body { margin: 0 }"
    html = weasyprint.HTML(string=f"<style>{page}</style><p>{body}</p>")
    document = diagram_fit.render_fitted(html, diagram_fit.FitSettings(min_font_pt=7))
    parts = [
        element for element in html.etree_element.iter() if element.get("data-ope-fit") == "part"
    ]
    assert len(parts) >= 2
    assert len(document.pages) >= 2


def test_font_pt_reads_the_root_font_size() -> None:
    import xml.etree.ElementTree as ET

    element = ET.Element("svg", {"viewBox": "0 0 100 100", "font-size": "12"})
    assert diagram_fit.font_pt(element, 100) == pytest.approx(9)


QUADRANT = """quadrantChart
    title Garden projects
    x-axis Low effort --> High effort
    y-axis Low value --> High value
    quadrant-1 Big bets
    Drip irrigation for the orchard 90 h: [0.7, 0.8]
    Herb spiral: [0.2, 0.3]"""


def _font_sizes(svg: str, cls: str) -> list[str]:
    return re.findall(rf'<(?:text|g) class="{cls}"[^>]*font-size="([\d.]+)"', svg)


def test_quadrant_point_labels_stay_on_one_line() -> None:
    with PeleRenderer(PeleTheme()) as renderer:
        svg = renderer.render(QUADRANT, {"responsive": False, "fontSize": 22}).svg
    labels = svg[svg.index('class="pele-point-labels"') :]
    assert "<tspan" not in labels
    assert ">Drip irrigation for the orchard 90 h</text>" in labels


def test_quadrant_font_sizes_from_the_config() -> None:
    config = {
        "quadrantChart": {
            "titleFontSize": 25,
            "quadrantLabelFontSize": 19,
            "xAxisLabelFontSize": 15,
            "yAxisLabelFontSize": 13,
            "pointLabelFontSize": 11,
        }
    }
    with PeleRenderer(PeleTheme()) as renderer:
        svg = renderer.render(QUADRANT, {"responsive": False, "config": config}).svg
    assert _font_sizes(svg, "pele-title") == ["25"]
    assert _font_sizes(svg, "pele-label")[0] == "19"
    assert _font_sizes(svg, "pele-axis-labels") == ["15"]
    assert re.findall(r'rotate\(-90\)" font-size="([\d.]+)"', svg) == ["13", "13"]
    assert _font_sizes(svg, "pele-point-labels") == ["11"]


def test_quadrant_font_sizes_follow_font_size_without_config() -> None:
    with PeleRenderer(PeleTheme()) as renderer:
        svg = renderer.render(QUADRANT, {"responsive": False, "fontSize": 20}).svg
    assert _font_sizes(svg, "pele-title") == ["20"]
    assert _font_sizes(svg, "pele-axis-labels") == ["18"]
    assert _font_sizes(svg, "pele-point-labels") == ["15"]


def test_patch_fails_on_another_build() -> None:
    with pytest.raises(mermaid_pele.PeleUnavailableError):
        mermaid_pele.patch_pele("var pele = {};")


# ---- Vendored build ---------------------------------------------------------


def test_vendored_build_carries_its_license() -> None:
    text = mermaid_pele._asset()
    header = text[: text.index("*/")]
    assert f"Pele {mermaid_pele.PELE_VERSION}" in header
    assert "MIT License" in header
    assert "Lucide" in header
    assert "ISC License" in header


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_wide_chart_stays_on_a_portrait_page_with_its_heading(tmp_path: Path) -> None:
    import json

    import pypdfium2
    from typer.testing import CliRunner

    from obsidian_pdf_exporter.main import app

    vault = tmp_path / "Report"
    vault.mkdir()
    filler = "\n\n".join(f"Paragraph {i} " + "with some words " * 12 for i in range(8))
    chart = (
        'xychart-beta horizontal\n  x-axis ["Alpha", "Beta", "Gamma", "Delta"]\n'
        "  bar [23, 53, 55, 168]\n  bar [51, 42, 38, 31]"
    )
    note = f"# Report\n\n{filler}\n\n## Results\n\n{_block(chart)}\n"
    (vault / "Report.md").write_text(note, encoding="utf-8")
    config = tmp_path / "mermaid.json"
    config.write_text(json.dumps({"xyChart": {"width": 700, "height": 420}}), encoding="utf-8")
    pdf = tmp_path / "out.pdf"
    args = ["export", str(vault), "-o", str(pdf), "--no-toc", "-O", f"mermaid.config={config}"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output

    document = pypdfium2.PdfDocument(str(pdf))
    pages = [page.get_textpage().get_text_range() for page in document]
    assert all(page.get_height() > page.get_width() for page in document)
    [with_heading] = [text for text in pages if "Results" in text]
    assert "Delta" in with_heading
