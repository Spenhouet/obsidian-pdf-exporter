"""Tests for mapping Mermaid themeVariables to Pele."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.core.html_postprocess import inline_svg_images
from obsidian_pdf_exporter.core.mermaid import MermaidSettings
from obsidian_pdf_exporter.core.mermaid import render_mermaid_blocks
from obsidian_pdf_exporter.core.mermaid_theme import diagram_css
from obsidian_pdf_exporter.core.mermaid_theme import diagram_variables
from obsidian_pdf_exporter.core.mermaid_theme import flat_theme
from obsidian_pdf_exporter.core.mermaid_theme import mark_svg
from obsidian_pdf_exporter.core.mermaid_theme import unused_keys

if TYPE_CHECKING:
    from pathlib import Path

GANTT = (
    "gantt\n  dateFormat YYYY-MM-DD\n"
    "  Release :milestone, 2027-01-10, 0d\n"
    "  Short :done, 2027-01-01, 2027-01-02\n"
    "  Long task :2027-01-01, 2027-03-31\n"
)
TIMELINE = "timeline\n  2027 : Start\n  2028 : Next : Later\n"
QUADRANT = "quadrantChart\n  quadrant-1 Do\n  Item A: [0.7, 0.8]\n"


def _render(tmp_path: Path, code: str, theme_vars: dict[str, object]) -> str:
    settings = MermaidSettings(config={"theme": "base", "themeVariables": theme_vars})
    out = render_mermaid_blocks(f"```mermaid\n{code}\n```", tmp_path, settings)
    [name] = re.findall(r"!\[\]\((mermaid-[0-9a-f]+\.svg)\)", out)
    return (tmp_path / name).read_text(encoding="utf-8")


def test_flat_theme_flattens_and_later_config_wins() -> None:
    config = {"themeVariables": {"taskBkgColor": "#111", "xyChart": {"titleColor": "#222"}}}
    front = {"themeVariables": {"taskBkgColor": "#333"}}
    assert flat_theme(config, front) == {"taskBkgColor": "#333", "xyChart.titleColor": "#222"}


def test_flowchart_variables_follow_mermaid_fallbacks() -> None:
    theme = {"primaryColor": "#eef", "nodeBorder": "#00a", "primaryBorderColor": "#999"}
    assert diagram_variables("flowchart", theme) == {
        "--pele-surface": "#eef",
        "--pele-border": "#00a",
    }
    assert diagram_variables("gantt", theme) == {}
    assert diagram_variables("gantt", {"lineColor": "#123"}) == {"--pele-line": "#123"}


def test_unsafe_values_are_skipped() -> None:
    assert diagram_css("pie", {"pieStrokeColor": "red} * { fill: red"}) == ()


def test_gantt_task_color_leaves_done_tasks_alone() -> None:
    rules = dict(diagram_css("gantt", {"taskBkgColor": "#f2b8bb"}))
    [selector] = [s for s in rules if s.endswith(" rect")]
    assert ":not(.pele-done)" in selector
    assert rules[selector] == "fill: #f2b8bb"


def test_mark_svg_tells_inside_from_outside_labels() -> None:
    svg = (
        '<g class="pele-task" data-id="a"><rect x="10" y="0" width="100" height="20"/>'
        '<text class="pele-label" fill="var(--_bg)" x="60" y="15">In</text></g>'
        '<g class="pele-task" data-id="b"><rect x="10" y="0" width="20" height="20"/>'
        '<text class="pele-label" x="80" y="15">Out</text></g>'
        '<g class="pele-task pele-milestone" data-id="c"><path d="M0,0Z"/>'
        '<text class="pele-label" x="5" y="15">Mile</text></g>'
    )
    marked = mark_svg(svg)
    assert re.findall(r'class="pele-label (ope-\w+)"', marked) == [
        "ope-inside",
        "ope-outside",
        "ope-outside",
    ]


def test_gantt_colors_reach_the_svg(tmp_path: Path) -> None:
    svg = _render(
        tmp_path,
        GANTT,
        {"taskBkgColor": "#F2B8BB", "taskTextColor": "#1A1A1A", "doneTaskBkgColor": "#E3E6E9"},
    )
    root = re.search(r"<svg\b[^>]*>", svg)
    assert root
    scope = re.search(r' id="(ope-[0-9a-f]+)"', root.group(0))
    assert scope
    style = re.search(r"<style>(.*?)</style>", svg)
    assert style
    assert f"#{scope.group(1)} .pele-task.pele-done rect {{ fill: #E3E6E9 }}" in style.group(1)
    assert "ope-inside" in svg
    assert "var(" not in svg


def test_timeline_cscale_sets_period_colors(tmp_path: Path) -> None:
    svg = _render(
        tmp_path, TIMELINE, {"cScale0": "#F2B8BB", "cScale1": "#E3E6E9", "cScaleLabel0": "#111"}
    )
    assert 'fill="#F2B8BB"' in svg
    assert 'fill="#E3E6E9"' in svg
    assert "ope-series-1" in svg
    assert ".ope-series-1 text { fill: #111 }" in svg
    assert ".ope-series-1 .pele-event rect { fill-opacity: 1 }" in svg


def test_quadrant_colors(tmp_path: Path) -> None:
    svg = _render(tmp_path, QUADRANT, {"quadrant1Fill": "#FBE3E4", "quadrantPointFill": "#CE1F26"})
    assert '.pele-quadrant[data-id="1"] rect { fill: #FBE3E4 }' in svg
    assert ".pele-point { fill: #CE1F26 }" in svg


def test_theme_changes_the_image_name(tmp_path: Path) -> None:
    first = _render(tmp_path, QUADRANT, {"quadrantPointFill": "#CE1F26"})
    second = _render(tmp_path, QUADRANT, {"quadrantPointFill": "#00AA00"})
    assert first != second
    assert len(list(tmp_path.glob("mermaid-*.svg"))) == 2


def test_style_survives_inlining(tmp_path: Path) -> None:
    svg = _render(tmp_path, QUADRANT, {"quadrantPointFill": "#CE1F26"})
    name = next(tmp_path.glob("mermaid-*.svg")).name
    html = inline_svg_images(f'<img class="doc-image mermaid" src="{name}">', tmp_path)
    scope = re.search(r' id="(ope-[0-9a-f]+)"', svg)
    assert scope
    assert f' id="{scope.group(1)}"' in html
    assert f"#{scope.group(1)} .pele-point" in html


def test_unused_keys() -> None:
    config = {
        "theme": "base",
        "themeCSS": ".x {}",
        "themeVariables": {
            "taskBkgColor": "#fff",
            "milestoneBkgColor": "#c00",
            "cScale0": "#fff",
            "cScale9": "#fff",
            "pie1": "#fff",
            "fontSize": "20px",
            "xyChart": {"plotColorPalette": "#fff", "backgroundColor": "#fff"},
        },
        "quadrantChart": {"chartWidth": 600, "pointLabelFontSize": 18, "useMaxWidth": True},
        "xyChart": {"width": 700, "titleFontSize": 18, "xAxis": {"showTick": False}},
        "flowchart": {"curve": "basis"},
    }
    assert unused_keys(config) == [
        "themeCSS",
        "themeVariables.milestoneBkgColor",
        "themeVariables.cScale9",
        "themeVariables.xyChart.backgroundColor",
        "xyChart.titleFontSize",
    ]
    assert unused_keys({"theme": "dark"}) == ["theme"]


def test_unused_keys_warn_once(tmp_path: Path) -> None:
    messages: list[str] = []
    config = {"themeVariables": {"pieOuterStrokeColor": "#fff"}}
    md = "\n\n".join(f"```mermaid\n{code}\n```" for code in (QUADRANT, TIMELINE))
    render_mermaid_blocks(md, tmp_path, MermaidSettings(config=config), log=messages.append)
    warnings = [m for m in messages if "themeVariables.pieOuterStrokeColor" in m]
    assert len(warnings) == 1
