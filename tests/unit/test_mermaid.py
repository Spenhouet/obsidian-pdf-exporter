"""Tests for rendering Mermaid code blocks."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter.core import mermaid
from obsidian_pdf_exporter.core import mermaid_pele
from obsidian_pdf_exporter.core.mermaid import MermaidSettings
from obsidian_pdf_exporter.core.mermaid import mermaid_settings
from obsidian_pdf_exporter.core.mermaid import render_mermaid_blocks
from obsidian_pdf_exporter.templates import load_from_path

if TYPE_CHECKING:
    from pathlib import Path

FLOWCHART = "graph LR\n  A-->B"


def _block(code: str, fence: str = "```") -> str:
    return f"{fence}mermaid\n{code}\n{fence}"


def test_markdown_without_mermaid_is_unchanged(tmp_path: Path) -> None:
    md = "# Title\n\n```python\nprint(1)\n```\n"
    assert render_mermaid_blocks(md, tmp_path, MermaidSettings()) == md
    assert list(tmp_path.iterdir()) == []


def test_blocks_are_replaced_by_svg_images(tmp_path: Path) -> None:
    pie = _block('pie\n  "A" : 1')
    graph = _block(FLOWCHART, "~~~")
    md = f"Intro\n\n{pie}\n\nMiddle\n\n{graph}\n"
    out = render_mermaid_blocks(md, tmp_path, MermaidSettings())

    images = re.findall(r"!\[\]\((mermaid-[0-9a-f]+\.svg)\)\{\.doc-image \.mermaid ([^}]*)\}", out)
    assert [kind for _, kind in images] == [".mermaid-pie", ".mermaid-flowchart"]
    assert "```" not in out
    assert "~~~" not in out
    for name, _ in images:
        assert (tmp_path / name).read_text(encoding="utf-8").startswith("<svg")


def test_identical_blocks_render_once(tmp_path: Path) -> None:
    block = _block(FLOWCHART)
    messages: list[str] = []
    out = render_mermaid_blocks(
        f"{block}\n\n{block}\n", tmp_path, MermaidSettings(), log=messages.append
    )
    assert len(set(re.findall(r"mermaid-[0-9a-f]+\.svg", out))) == 1
    assert len(re.findall(r"mermaid-[0-9a-f]+\.svg", out)) == 2
    assert any("Rendering 1 Mermaid diagram(s) with Pele" in m for m in messages)


def test_failed_block_stays_as_code(tmp_path: Path) -> None:
    good = _block(FLOWCHART)
    bad = _block("flowchart LR\n  A --> ((")
    messages: list[str] = []
    out = render_mermaid_blocks(
        f"{good}\n\n{bad}\n", tmp_path, MermaidSettings(), log=messages.append
    )

    assert bad in out
    assert good not in out
    assert re.search(r"mermaid-[0-9a-f]+\.svg", out)
    assert any("Pele could not draw a flowchart diagram" in m for m in messages)
    assert any("1 Mermaid block(s) could not be drawn and stay as code" in m for m in messages)


def test_pele_unavailable_keeps_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> None:
        msg = "Pele could not be loaded: broken"
        raise mermaid_pele.PeleUnavailableError(msg)

    monkeypatch.setattr(mermaid_pele.PeleRenderer, "__init__", unavailable)
    messages: list[str] = []
    md = _block(FLOWCHART)
    assert render_mermaid_blocks(md, tmp_path, MermaidSettings(), log=messages.append) == md
    assert any("Warning: Pele could not be loaded" in m for m in messages)
    assert any("1 Mermaid block(s) could not be drawn" in m for m in messages)


def test_strip_comments_keeps_directives() -> None:
    code = '%%{init: {"theme": "dark"}}%%\npie\n  %% a comment\n%% ope: width=8cm\n  "A" : 1'
    assert mermaid.strip_comments(code) == '%%{init: {"theme": "dark"}}%%\npie\n  "A" : 1'


def test_max_height_sets_width_attribute(tmp_path: Path) -> None:
    out = render_mermaid_blocks(_block(FLOWCHART), tmp_path, MermaidSettings())
    assert "width=" not in out
    name = re.search(r"mermaid-[0-9a-f]+\.svg", out)
    assert name
    size = mermaid._natural_size(tmp_path / name.group(0))
    assert size
    width, height = size

    half = f"{height / 2:.3f}px"
    out = render_mermaid_blocks(
        _block(FLOWCHART), tmp_path, mermaid_settings({"mermaid.max_height": half})
    )
    assert f" width={width / 2:.0f}}}" in out
    out = render_mermaid_blocks(
        _block(FLOWCHART), tmp_path, mermaid_settings({"mermaid.max_height": "10cm"})
    )
    assert "width=" not in out


def test_comment_lines_do_not_change_the_diagram(tmp_path: Path) -> None:
    plain = _block(FLOWCHART)
    commented = _block("%% ope: width=4cm\ngraph LR\n  %% note\n  A-->B")
    out = render_mermaid_blocks(f"{plain}\n\n{commented}\n", tmp_path, MermaidSettings())
    assert len(set(re.findall(r"mermaid-[0-9a-f]+\.svg", out))) == 1
    assert "style=" not in out
    assert len(list(tmp_path.glob("mermaid-*.svg"))) == 1


def test_settings_reject_bad_max_height() -> None:
    with pytest.raises(ValueError, match="max_height"):
        mermaid_settings({"mermaid.max_height": "50%"})


def test_disabled_keeps_blocks(tmp_path: Path) -> None:
    md = _block(FLOWCHART)
    settings = mermaid_settings({"mermaid": "off"})
    assert render_mermaid_blocks(md, tmp_path, settings) == md
    assert list(tmp_path.iterdir()) == []


def test_settings_fit_is_on_by_default() -> None:
    assert mermaid_settings({}).fit
    assert not mermaid_settings({"mermaid.fit": "off"}).fit


def test_settings_merge_template_file_and_theme(tmp_path: Path) -> None:
    config_file = tmp_path / "mermaid.json"
    config_file.write_text(
        json.dumps({"theme": "forest", "themeVariables": {"pie1": "#111111"}}),
        encoding="utf-8",
    )
    template = {"theme": "base", "themeVariables": {"pie1": "#000000", "pie2": "#222222"}}
    settings = mermaid_settings(
        {"mermaid.config": str(config_file)},
        template,
    )
    assert settings.enabled
    assert settings.config == {
        "theme": "forest",
        "themeVariables": {"pie1": "#111111", "pie2": "#222222"},
    }
    assert template["themeVariables"]["pie1"] == "#000000"  # input left alone


def test_removed_mermaid_cli_options_warn(tmp_path: Path) -> None:
    settings = mermaid_settings(
        {"mermaid.renderer": "mermaid-cli", "mermaid.format": "png", "mermaid.cli": "mmdc"}
    )
    assert settings.ignored == [
        "mermaid.renderer=mermaid-cli",
        "mermaid.format=png",
        "mermaid.cli=mmdc",
    ]
    messages: list[str] = []
    out = render_mermaid_blocks(_block(FLOWCHART), tmp_path, settings, log=messages.append)
    assert re.search(r"mermaid-[0-9a-f]+\.svg", out)
    warnings = [m for m in messages if "has no effect" in m]
    assert len(warnings) == 3
    assert all(m.startswith("  Warning: -O mermaid.") for m in warnings)


def test_pele_renderer_option_is_quiet() -> None:
    options = {"mermaid.renderer": "Pele", "mermaid.format": "svg"}
    assert mermaid_settings(options).ignored == []


def test_filesystem_template_reads_mermaid_config(tmp_path: Path) -> None:
    (tmp_path / "template.css").write_text("body {}", encoding="utf-8")
    (tmp_path / "template.yaml").write_text(
        "mermaid:\n  theme: base\n  themeVariables:\n    pie1: '#123456'\n", encoding="utf-8"
    )
    tpl = load_from_path(tmp_path)
    assert tpl.mermaid_config(None) == {"theme": "base", "themeVariables": {"pie1": "#123456"}}


def test_filesystem_template_rejects_non_mapping_mermaid(tmp_path: Path) -> None:
    (tmp_path / "template.css").write_text("body {}", encoding="utf-8")
    (tmp_path / "template.yaml").write_text("mermaid: dark\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mermaid"):
        load_from_path(tmp_path)


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ('pie\n  "A" : 1', "pie"),
        ('pie title Fruit\n  "A" : 1', "pie"),
        ("graph LR\n  A-->B", "flowchart"),
        ("flowchart TD\n  A-->B", "flowchart"),
        ("sequenceDiagram\n  A->>B: hi", "sequenceDiagram"),
        ("quadrantChart\n  title Q", "quadrantChart"),
        ("xychart-beta\n  x-axis [a, b]", "xychart-beta"),
        ("---\ntitle: Plan\n---\n%% comment\n%%{init: {}}%%\n\ngantt\n  title G", "gantt"),
        ("%% only a comment", ""),
        ("---\ntitle: never closed", ""),
        ("", ""),
    ],
)
def test_diagram_type(code: str, kind: str) -> None:
    assert mermaid.diagram_type(code) == kind


def test_inlined_svg_gets_width_attribute_not_style(tmp_path: Path) -> None:
    from obsidian_pdf_exporter.core.html_postprocess import inline_svg_images

    (tmp_path / "d.svg").write_text('<svg width="300" viewBox="0 0 300 100"></svg>', "utf-8")
    html = inline_svg_images(
        '<img src="d.svg" class="mermaid mermaid-pie" width="128" />', tmp_path
    )
    assert html == (
        '<svg class="mermaid mermaid-pie" style="max-width:100%;" width="128" '
        'viewBox="0 0 300 100"></svg>'
    )
