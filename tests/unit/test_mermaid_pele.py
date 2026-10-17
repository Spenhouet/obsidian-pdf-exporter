"""Tests for drawing Mermaid diagrams with Pele in the embedded V8 engine.

None of these tests needs Node.js. The comparison with mermaid-cli at the end
runs only when mermaid-cli is available, like the other real-CLI tests.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
from tests.unit.test_mermaid import _REAL_CLI
from tests.unit.test_mermaid import FakeMermaidCli

PELE = MermaidSettings(renderer="pele")
FLOWCHART = "flowchart LR\n  A[Collect data] -->|then| B{Valid?}"


def _block(code: str) -> str:
    return f"```mermaid\n{code}\n```"


def _images(markdown: str) -> list[tuple[str, str]]:
    return re.findall(r"!\[\]\((mermaid-[0-9a-f]+\.svg)\)\{([^}]*)\}", markdown)


@pytest.fixture
def no_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mermaid, "find_mermaid_cli", lambda _override="": None)


@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch) -> FakeMermaidCli:
    fake = FakeMermaidCli()
    monkeypatch.setattr(mermaid, "find_mermaid_cli", lambda _override="": ["mmdc"])
    monkeypatch.setattr(mermaid.subprocess, "run", fake)
    return fake


# ---- Settings ---------------------------------------------------------------


def test_renderer_defaults_to_mermaid_cli() -> None:
    assert mermaid_settings({}).renderer == "mermaid-cli"
    assert mermaid_settings({"mermaid.renderer": "Pele"}).renderer == "pele"


def test_settings_reject_unknown_renderer() -> None:
    with pytest.raises(ValueError, match=r"mermaid\.renderer"):
        mermaid_settings({"mermaid.renderer": "browser"})


# ---- Rendering --------------------------------------------------------------


@pytest.mark.usefixtures("no_cli")
def test_pele_renders_without_node(tmp_path: Path) -> None:
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


@pytest.mark.usefixtures("no_cli")
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


@pytest.mark.usefixtures("no_cli")
def test_pele_output_is_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    render_mermaid_blocks(_block(FLOWCHART), tmp_path, PELE)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    monkeypatch.setattr(mermaid_pele.PeleRenderer, "__init__", fail)
    assert _images(render_mermaid_blocks(_block(FLOWCHART), tmp_path, PELE))


def test_pele_failure_falls_back_to_mermaid_cli(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    messages: list[str] = []
    bad = "flowchart LR\n  A --> (("
    md = f"{_block(FLOWCHART)}\n\n{_block(bad)}\n"
    out = render_mermaid_blocks(md, tmp_path, PELE, log=messages.append)

    assert len(_images(out)) == 2
    assert "```mermaid" not in out
    batch = fake_cli.calls[0][fake_cli.calls[0].index("-i") + 1]
    assert Path(batch).read_text(encoding="utf-8").count("```mermaid") == 1
    assert any("Pele could not draw a flowchart diagram" in m for m in messages)
    assert any("1 Mermaid diagram(s) with mermaid-cli" in m for m in messages)


@pytest.mark.usefixtures("no_cli")
def test_pele_failure_without_mermaid_cli_keeps_code(tmp_path: Path) -> None:
    messages: list[str] = []
    bad = _block("flowchart LR\n  A --> ((")
    out = render_mermaid_blocks(bad, tmp_path, PELE, log=messages.append)

    assert out == bad
    assert any(m.startswith("  Warning: Pele could not draw") for m in messages)
    assert any("could not be drawn by Pele and stay as code" in m for m in messages)


@pytest.mark.usefixtures("no_cli")
def test_unknown_diagram_type_falls_back(tmp_path: Path) -> None:
    messages: list[str] = []
    out = render_mermaid_blocks(_block("notADiagram\n  x"), tmp_path, PELE, log=messages.append)
    assert "```mermaid" in out
    assert any("Pele could not draw" in m for m in messages)


def test_closing_br_tag_breaks_the_line() -> None:
    with PeleRenderer(PeleTheme()) as renderer:
        result = renderer.render('flowchart LR\n  A["Local</br>Database"]', {"responsive": False})
    assert "<tspan" in result.svg
    assert "LocalDatabase" not in result.svg


@pytest.mark.usefixtures("no_cli")
def test_wide_pele_diagram_goes_to_landscape(tmp_path: Path) -> None:
    chain = " --> ".join(f"N{i}[Step number {i}]" for i in range(12))
    out = render_mermaid_blocks(_block(f"flowchart LR\n  {chain}"), tmp_path, PELE)
    [(_name, attrs)] = _images(out)
    assert ".landscape" in attrs


@pytest.mark.usefixtures("no_cli")
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


@pytest.mark.usefixtures("no_cli")
def test_theme_colors_end_up_in_the_svg(tmp_path: Path) -> None:
    out = render_mermaid_blocks(_block(FLOWCHART), tmp_path, PELE, css=TEMPLATE_CSS)
    [(name, _attrs)] = _images(out)
    svg = (tmp_path / name).read_text(encoding="utf-8")
    assert 'fill="#eef2f7"' in svg
    assert "font-family=\"'Inter', 'Arial', sans-serif\"" in svg
    assert 'color="#222222"' in svg


@pytest.mark.usefixtures("no_cli")
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
    widths = measurer.widths(["0|Hello world", "1|Hello world", "4|Hello world", "0|"])
    assert widths["0|Hello world"] > 0
    assert widths["1|Hello world"] >= widths["0|Hello world"]
    assert widths["4|Hello world"] > 0
    assert widths["0|"] == 0


def test_labels_are_measured_in_the_diagram_font() -> None:
    """A label box is as wide as Pango measures the label, plus Pele's padding."""
    label = "Collect all data"
    code = f"flowchart LR\n  A[{label}]"
    measurer = mermaid_pele._PangoMeasurer(PeleTheme())
    if not measurer.available():
        pytest.skip("Pango is not available")
    with PeleRenderer(PeleTheme()) as renderer:
        svg = renderer.render(code, {"responsive": False, "padding": 0}).svg
    text_width = measurer.widths([f"0|{label}"])[f"0|{label}"] * 16
    box = re.search(r'<rect x="[-\d.]+" y="[-\d.]+" width="([\d.]+)"', svg)
    assert box
    padding = float(box.group(1)) - text_width
    assert 0 < padding < 60


# ---- Layout -----------------------------------------------------------------


@pytest.mark.usefixtures("no_cli")
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


# ---- Vendored build ---------------------------------------------------------


def test_vendored_build_carries_its_license() -> None:
    text = mermaid_pele._asset()
    header = text[: text.index("*/")]
    assert f"Pele {mermaid_pele.PELE_VERSION}" in header
    assert "MIT License" in header
    assert "Lucide" in header
    assert "ISC License" in header


# ---- Real mermaid-cli -------------------------------------------------------


@pytest.mark.skipif(not _REAL_CLI, reason="mermaid-cli not available")
def test_real_cli_and_pele_draw_the_same_labels(tmp_path: Path) -> None:
    """Both renderers draw every word of the labels of the same diagram."""
    texts: dict[str, Any] = {}
    for renderer in ("mermaid-cli", "pele"):
        build = tmp_path / renderer
        build.mkdir()
        settings = mermaid_settings({"mermaid.renderer": renderer, "mermaid.cli": _REAL_CLI})
        out = render_mermaid_blocks(_block(FLOWCHART), build, settings)
        [(name, _attrs)] = _images(out)
        texts[renderer] = (build / name).read_text(encoding="utf-8")
    for svg in texts.values():
        # mermaid-cli puts every word of a label in a tspan of its own.
        for word in ("Collect", "data", "Valid?", "then"):
            assert f">{word}<" in svg or f"{word} " in svg or f" {word}" in svg
