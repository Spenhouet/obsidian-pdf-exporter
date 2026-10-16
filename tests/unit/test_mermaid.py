"""Tests for rendering Mermaid code blocks."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from PIL import ImageDraw

from obsidian_pdf_exporter.core import mermaid
from obsidian_pdf_exporter.core.mermaid import MermaidSettings
from obsidian_pdf_exporter.core.mermaid import find_mermaid_cli
from obsidian_pdf_exporter.core.mermaid import mermaid_settings
from obsidian_pdf_exporter.core.mermaid import render_mermaid_blocks
from obsidian_pdf_exporter.templates import load_from_path

FAKE_SVG = (
    '<svg id="my-svg" width="100%" style="max-width: 300px;" viewBox="0 0 300 100">'
    "<style>#my-svg{fill:#333;}</style></svg>"
)


def _png(path: Path, *, transparent: bool) -> None:
    """Write a 900x300 PNG with content from 10% to 90% in both directions."""
    background = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
    image = Image.new("RGBA", (900, 300), background)
    ImageDraw.Draw(image).rectangle((90, 30, 809, 269), fill=(20, 40, 60, 255))
    image.save(path)


class FakeMermaidCli:
    """Stand-in for mermaid-cli. Fails on any diagram that contains ``FAIL``."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append(argv)
        src = Path(argv[argv.index("-i") + 1])
        out = Path(argv[argv.index("-o") + 1])
        ext = argv[argv.index("-e") + 1]
        text = src.read_text(encoding="utf-8")
        if "FAIL" in text:
            return subprocess.CompletedProcess(argv, 1, "", "Error: Parse error on line 1:\n")
        count = len(re.findall("```mermaid", text)) if src.suffix == ".md" else 0
        targets = [out.with_name(f"{out.stem}-{i}.{ext}") for i in range(1, count + 1)]
        for target in targets or [out]:
            if ext == "png":
                _png(target, transparent=argv[argv.index("-b") + 1] == "transparent")
            else:
                target.write_text(FAKE_SVG, encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def config(self) -> dict:
        argv = self.calls[0]
        return json.loads(Path(argv[argv.index("-c") + 1]).read_text(encoding="utf-8"))


@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch) -> FakeMermaidCli:
    fake = FakeMermaidCli()
    monkeypatch.setattr(mermaid, "find_mermaid_cli", lambda _override="": ["mmdc"])
    monkeypatch.setattr(mermaid.subprocess, "run", fake)
    return fake


def _block(code: str, fence: str = "```") -> str:
    return f"{fence}mermaid\n{code}\n{fence}"


def test_markdown_without_mermaid_is_unchanged(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    md = "# Title\n\n```python\nprint(1)\n```\n"
    assert render_mermaid_blocks(md, tmp_path, MermaidSettings()) == md
    assert fake_cli.calls == []


def test_blocks_are_replaced_by_svg_images(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    pie = _block('pie\n  "A" : 1')
    graph = _block("graph LR\n  A-->B", "~~~")
    md = f"Intro\n\n{pie}\n\nMiddle\n\n{graph}\n"
    out = render_mermaid_blocks(md, tmp_path, MermaidSettings())

    images = re.findall(r"!\[\]\((mermaid-[0-9a-f]+\.svg)\)\{\.doc-image \.mermaid ([^}]*)\}", out)
    assert [kind for _, kind in images] == [".mermaid-pie", ".mermaid-flowchart"]
    images = [name for name, _ in images]
    assert "```" not in out
    assert "~~~" not in out
    assert len(fake_cli.calls) == 2  # one run for all diagrams, one to measure them
    svg = (tmp_path / images[0]).read_text(encoding="utf-8")
    digest = images[0][len("mermaid-") : -len(".svg")]
    assert "my-svg" not in svg
    assert f'id="mermaid-{digest}"' in svg
    assert f"#mermaid-{digest}{{" in svg
    assert '<svg id="mermaid-' in svg
    assert 'width="256"' in svg
    assert 'viewBox="22 2 256 96"' in svg
    assert "max-width" not in svg


def test_svg_config_turns_off_html_labels(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    settings = MermaidSettings(
        config={"htmlLabels": True, "flowchart": {"curve": "basis"}, "themeCSS": ".x{}"}
    )
    render_mermaid_blocks(_block("graph LR\n  A-->B"), tmp_path, settings)
    config = fake_cli.config()
    assert config["htmlLabels"] is False
    assert config["flowchart"] == {"curve": "basis", "htmlLabels": False}
    assert config["themeCSS"].startswith(".x{} ")
    assert ".tick{opacity:1" in config["themeCSS"]


def test_identical_blocks_render_once(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    block = _block("graph LR\n  A-->B")
    out = render_mermaid_blocks(f"{block}\n\n{block}\n", tmp_path, MermaidSettings())
    batch = fake_cli.calls[0][fake_cli.calls[0].index("-i") + 1]
    assert Path(batch).read_text(encoding="utf-8").count("```mermaid") == 1
    assert len(set(re.findall(r"mermaid-[0-9a-f]+\.svg", out))) == 1


def test_failed_block_stays_as_code(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    good = _block("graph LR\n  A-->B")
    bad = _block("FAIL ((")
    messages: list[str] = []
    out = render_mermaid_blocks(
        f"{good}\n\n{bad}\n", tmp_path, MermaidSettings(), log=messages.append
    )

    assert bad in out
    assert good not in out
    assert re.search(r"mermaid-[0-9a-f]+\.svg", out)
    # failed batch, one run per diagram, then one run to measure the good one
    assert len(fake_cli.calls) == 4
    assert any("Parse error" in m for m in messages)
    assert any("1 Mermaid block(s) could not be rendered" in m for m in messages)


def test_png_output_sets_width_attribute(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    settings = MermaidSettings(image_format="png", scale=3, config={"htmlLabels": True}, trim=False)
    out = render_mermaid_blocks(_block("graph LR\n  A-->B"), tmp_path, settings)
    assert re.fullmatch(
        r"!\[\]\(mermaid-[0-9a-f]+\.png\)\{\.doc-image \.mermaid \.mermaid-flowchart width=300\}",
        out,
    )
    argv = fake_cli.calls[0]
    assert argv[argv.index("-s") + 1] == "3"
    assert fake_cli.config() == {"htmlLabels": True}


def test_svg_text_keeps_only_the_tspan_line_offset() -> None:
    svg = (
        '<svg id="my-svg" viewBox="0 0 10 10">'
        '<text dy="1em" text-anchor="middle"><tspan x="0" dy="1em">Two</tspan>'
        '<tspan x="0" dy="1.1em">lines</tspan></text>'
        '<text y="5" dy="1em">Plain</text></svg>'
    )
    out = mermaid._tidy_svg(svg, "abc")
    assert '<text text-anchor="middle"><tspan x="0" dy="1em">Two</tspan>' in out
    assert '<tspan x="0" dy="1.1em">lines</tspan>' in out
    assert '<text y="5" dy="1em">Plain</text>' in out


def test_trim_off_keeps_svg_size(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    out = render_mermaid_blocks(_block("graph LR\n  A-->B"), tmp_path, MermaidSettings(trim=False))
    image = re.search(r"mermaid-[0-9a-f]+\.svg", out)
    assert image
    svg = (tmp_path / image.group(0)).read_text(encoding="utf-8")
    assert 'width="300"' in svg
    assert 'viewBox="0 0 300 100"' in svg
    assert len(fake_cli.calls) == 1


def test_png_is_cropped_to_content(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    settings = MermaidSettings(image_format="png", scale=3)
    out = render_mermaid_blocks(_block("graph LR\n  A-->B"), tmp_path, settings)
    image = re.search(r"mermaid-[0-9a-f]+\.png", out)
    assert image
    with Image.open(tmp_path / image.group(0)) as png:
        # content is 720x240 px, plus 8 CSS px (24 px at scale 3) on each side
        assert png.size == (768, 288)
    assert " width=256}" in out
    assert len(fake_cli.calls) == 1


def test_strip_comments_keeps_directives() -> None:
    code = '%%{init: {"theme": "dark"}}%%\npie\n  %% a comment\n%% ope: width=8cm\n  "A" : 1'
    assert mermaid.strip_comments(code) == '%%{init: {"theme": "dark"}}%%\npie\n  "A" : 1'


@pytest.mark.parametrize(
    ("options", "style"),
    [
        ({}, None),
        ({"mermaid.max_height": "48px"}, "128"),  # 256x96 diagram
        ({"mermaid.max_height": "10cm"}, None),
    ],
)
def test_max_height_sets_width_attribute(
    tmp_path: Path,
    fake_cli: FakeMermaidCli,
    options: dict[str, str],
    style: str | None,
) -> None:
    out = render_mermaid_blocks(_block("graph LR\n  A-->B"), tmp_path, mermaid_settings(options))
    assert re.match(r"!\[\]\(mermaid-[0-9a-f]+\.svg\)", out)
    if style is None:
        assert "width=" not in out
    else:
        assert f" width={style}}}" in out
    assert len(fake_cli.calls) >= 1


def test_comment_lines_do_not_change_the_diagram(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    plain = _block("graph LR\n  A-->B")
    commented = _block("%% ope: width=4cm\ngraph LR\n  %% note\n  A-->B")
    out = render_mermaid_blocks(f"{plain}\n\n{commented}\n", tmp_path, MermaidSettings())
    assert len(set(re.findall(r"mermaid-[0-9a-f]+\.svg", out))) == 1
    assert "style=" not in out
    batch = fake_cli.calls[0][fake_cli.calls[0].index("-i") + 1]
    text = Path(batch).read_text(encoding="utf-8")
    assert text.count("```mermaid") == 1
    assert "%%" not in text


def test_settings_reject_bad_max_height() -> None:
    with pytest.raises(ValueError, match="max_height"):
        mermaid_settings({"mermaid.max_height": "50%"})


def test_without_renderer_blocks_stay_and_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mermaid.shutil, "which", lambda _name: None)
    messages: list[str] = []
    md = _block("graph LR\n  A-->B")
    assert render_mermaid_blocks(md, tmp_path, MermaidSettings(), log=messages.append) == md
    assert any("kept as code" in m for m in messages)


def test_disabled_keeps_blocks(tmp_path: Path, fake_cli: FakeMermaidCli) -> None:
    md = _block("graph LR\n  A-->B")
    settings = mermaid_settings({"mermaid": "off"})
    assert render_mermaid_blocks(md, tmp_path, settings) == md
    assert fake_cli.calls == []


def test_settings_merge_template_file_and_theme(tmp_path: Path) -> None:
    config_file = tmp_path / "mermaid.json"
    config_file.write_text(
        json.dumps({"theme": "forest", "themeVariables": {"pie1": "#111111"}}),
        encoding="utf-8",
    )
    template = {"theme": "base", "themeVariables": {"pie1": "#000000", "pie2": "#222222"}}
    settings = mermaid_settings(
        {
            "mermaid.config": str(config_file),
            "mermaid.theme": "neutral",
            "mermaid.format": "PNG",
            "mermaid.scale": "2",
        },
        template,
    )
    assert settings.enabled
    assert settings.image_format == "png"
    assert settings.scale == 2
    assert settings.config == {
        "theme": "neutral",
        "themeVariables": {"pie1": "#111111", "pie2": "#222222"},
    }
    assert template["themeVariables"]["pie1"] == "#000000"  # input left alone


def test_settings_reject_unknown_format() -> None:
    with pytest.raises(ValueError, match=r"mermaid\.format"):
        mermaid_settings({"mermaid.format": "gif"})


def test_find_mermaid_cli_order(monkeypatch: pytest.MonkeyPatch) -> None:
    found = {"mmdc": "/bin/mmdc", "npx": "/bin/npx"}
    monkeypatch.setattr(mermaid.shutil, "which", found.get)
    assert find_mermaid_cli("my-mmdc --quiet") == ["my-mmdc", "--quiet"]
    assert find_mermaid_cli() == ["/bin/mmdc"]
    del found["mmdc"]
    assert find_mermaid_cli() == ["/bin/npx", "-y", mermaid.MERMAID_CLI_PACKAGE]
    del found["npx"]
    assert find_mermaid_cli() is None


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


# ---- Real mermaid-cli ------------------------------------------------------
# Runs only when mermaid-cli is available: ``mmdc`` on the PATH, or a command
# in OPE_TEST_MERMAID_CLI (e.g. "npx -y @mermaid-js/mermaid-cli@11.4.2").

_REAL_CLI = os.environ.get("OPE_TEST_MERMAID_CLI") or shutil.which("mmdc") or ""

DIAGRAMS = {
    "pie": ('pie title Time spent\n  "Projects" : 60\n  "Operations" : 40', ["Projects"]),
    "quadrantChart": (
        "quadrantChart\n  title Effort and value\n  x-axis Low effort --> High effort\n"
        "  y-axis Low value --> High value\n  quadrant-1 Big bets\n  Alpha: [0.8, 0.7]",
        ["Big bets", "Alpha"],
    ),
    "gantt": (
        "gantt\n  dateFormat YYYY-MM-DD\n  axisFormat %b\n  section Phase A\n"
        "  Design :2027-01-01, 2027-03-31",
        ["Phase A", "Design", "Jan"],
    ),
    "flowchart": (
        "flowchart LR\n  A[Collect data] -->|then| B{Valid?}",
        ["Collect data", "Valid?", "then"],
    ),
    "timeline": (
        "timeline\n  title Rollout\n  2027 Q1 : Prototype ready for the first test users",
        ["Rollout", "Prototype", "users"],
    ),
}


@pytest.mark.skipif(not _REAL_CLI, reason="mermaid-cli not available")
def test_real_cli_renders_svg_without_foreign_object(tmp_path: Path) -> None:
    md = "\n\n".join(_block(code) for code, _ in DIAGRAMS.values())
    out = render_mermaid_blocks(md, tmp_path, MermaidSettings(cli=_REAL_CLI))

    images = re.findall(r"mermaid-[0-9a-f]+\.svg", out)
    assert len(images) == len(DIAGRAMS)
    for image, (name, (_, labels)) in zip(images, DIAGRAMS.items(), strict=True):
        svg = (tmp_path / image).read_text(encoding="utf-8")
        assert "foreignObject" not in svg, name
        # Labels are plain SVG text; flowcharts put each word in its own tspan.
        words = re.sub(r"<style>.*?</style>|<[^>]+>", " ", svg, flags=re.DOTALL).split()
        for word in " ".join(labels).split():
            assert word in words, (name, word)


@pytest.mark.skipif(not _REAL_CLI, reason="mermaid-cli not available")
def test_real_cli_timeline_text_has_one_line_offset(tmp_path: Path) -> None:
    code, _ = DIAGRAMS["timeline"]
    out = render_mermaid_blocks(_block(code), tmp_path, MermaidSettings(cli=_REAL_CLI))
    image = re.search(r"mermaid-[0-9a-f]+\.svg", out)
    assert image
    svg = (tmp_path / image.group(0)).read_text(encoding="utf-8")
    assert "<tspan" in svg
    assert not re.search(r'<text\b[^>]*\sdy="[^"]*"[^>]*>\s*<tspan\b[^>]*\sdy=', svg)


@pytest.mark.skipif(not _REAL_CLI, reason="mermaid-cli not available")
def test_real_cli_trims_svg(tmp_path: Path) -> None:
    code, _ = DIAGRAMS["pie"]
    widths = []
    for trim in (False, True):
        build = tmp_path / str(trim)
        build.mkdir()
        out = render_mermaid_blocks(_block(code), build, MermaidSettings(cli=_REAL_CLI, trim=trim))
        image = re.search(r"mermaid-[0-9a-f]+\.svg", out)
        assert image
        svg = (build / image.group(0)).read_text(encoding="utf-8")
        widths.append(float(re.search(r'<svg\b[^>]*\swidth="([\d.]+)"', svg).group(1)))
    assert 0 < widths[1] < widths[0]


@pytest.mark.skipif(not _REAL_CLI, reason="mermaid-cli not available")
def test_real_cli_renders_png(tmp_path: Path) -> None:
    code, _ = DIAGRAMS["flowchart"]
    settings = MermaidSettings(cli=_REAL_CLI, image_format="png", scale=2)
    out = render_mermaid_blocks(_block(code), tmp_path, settings)
    image = re.search(r"mermaid-[0-9a-f]+\.png", out)
    assert image
    assert (tmp_path / image.group(0)).read_bytes().startswith(b"\x89PNG")


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
