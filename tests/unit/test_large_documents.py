"""Tests for the work an export saves on large documents: embedded image data."""

from __future__ import annotations

import base64
import io
import shutil
from typing import TYPE_CHECKING
from urllib.parse import unquote

import pypdfium2
import pytest
from PIL import Image

from obsidian_pdf_exporter.core.html_postprocess import _RE_ID
from obsidian_pdf_exporter.core.html_postprocess import _RE_LOCAL_HREF
from obsidian_pdf_exporter.core.html_postprocess import unlink_missing_targets
from obsidian_pdf_exporter.core.html_postprocess import without_image_data
from obsidian_pdf_exporter.core.htmltree import HtmlTree
from obsidian_pdf_exporter.core.htmltree import unwrap
from obsidian_pdf_exporter.core.outside_links import outside_message
from obsidian_pdf_exporter.core.pandoc import render_html
from obsidian_pdf_exporter.core.pdf import html_to_pdf
from obsidian_pdf_exporter.core.pdf import images_to_files
from obsidian_pdf_exporter.core.pipeline import run_html
from obsidian_pdf_exporter.core.steps import core_steps
from obsidian_pdf_exporter.core.steps.base import DocumentContext

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")


def _png(color: tuple[int, int, int], size: tuple[int, int] = (40, 20)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _page_pixels(pdf: Path) -> list[bytes]:
    document = pypdfium2.PdfDocument(str(pdf))
    return [page.render(scale=1).to_pil().tobytes() for page in document]


def test_images_to_files_writes_each_image_once(tmp_path: Path) -> None:
    red = _png((255, 0, 0))
    html = f'<img src="data:image/png;base64,{red}"><img src="data:image/png;base64,{red}">'
    out = images_to_files(html, tmp_path)
    files = sorted(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == base64.b64decode(red)
    assert out.count(f'src="{files[0].as_uri()}"') == 2
    assert "base64" not in out


def test_images_to_files_keeps_svg_and_broken_data(tmp_path: Path) -> None:
    svg = base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'/>").decode("ascii")
    html = (
        f'<img src="data:image/svg+xml;base64,{svg}">'
        '<img src="data:image/png;base64,abc">'
        "<p>src=&quot;data:image/png;base64,AAAA&quot;</p>"
    )
    assert images_to_files(html, tmp_path) == html
    assert not list(tmp_path.iterdir())


def test_pdf_with_embedded_images_looks_the_same(tmp_path: Path) -> None:
    from weasyprint import HTML

    images = "".join(
        f'<p><img src="data:image/png;base64,{_png(c, (300 + 40 * k, 200))}"></p>'
        for k, c in enumerate([(200, 30, 30), (30, 200, 30), (200, 30, 30)])
    )
    table = f"<table><tr><td>{images}</td></tr></table>"
    html = f"<html><body><h1>Images</h1>{images}{table}</body></html>"
    reference = tmp_path / "reference.pdf"
    HTML(string=html).write_pdf(str(reference))
    exported = tmp_path / "exported.pdf"
    html_to_pdf(html, exported)
    assert _page_pixels(exported) == _page_pixels(reference)


def test_without_image_data_hides_and_restores_the_data() -> None:
    red = _png((255, 0, 0))
    svg = base64.b64encode(b"<svg/>").decode("ascii")
    html = (
        f'<p><img src="data:image/png;base64,{red}" width="10"></p>'
        f'<img src="data:image/svg+xml;base64,{svg}">'
    )
    seen: list[str] = []

    def process(text: str) -> str:
        seen.append(text)
        return text.replace("<p>", "<div>").replace("</p>", "</div>") + text

    out = without_image_data(html, process)
    assert red not in seen[0]
    assert svg in seen[0]
    assert 'src="data:image/png;base64,' in seen[0]
    assert out == process(html)


@needs_pandoc
def test_post_processing_without_image_data_gives_the_same_html(tmp_path: Path) -> None:
    for k, color in enumerate([(200, 30, 30), (30, 30, 200)]):
        (tmp_path / f"shot{k}.png").write_bytes(base64.b64decode(_png(color, (900, 300))))
    markdown = (
        "# Shots\n\n"
        "![first](shot0.png){width=300}\n\n"
        "| A | B | C | D | E | F |\n|---|---|---|---|---|---|\n"
        "| ![x](shot1.png) | long text that needs room | c | d | e | f |\n\n"
        "A note[^1] and a [missing link](#nowhere).\n\n"
        "- [x] done\n- [ ] open\n\n"
        "[^1]: The note.\n"
    )
    (tmp_path / "style.css").write_text("", encoding="utf-8")
    html = render_html(markdown, "style.css", "Shots", tmp_path)
    assert html.count("data:image/png;base64,") == 2
    context = DocumentContext(build_dir=tmp_path)
    steps = core_steps()

    def post(text: str) -> str:
        return unlink_missing_targets(run_html(text, context, steps))

    def post_stashed(text: str) -> str:
        return unlink_missing_targets(
            without_image_data(text, lambda t: run_html(t, context, steps))
        )

    assert post_stashed(html) == post(html)


def test_vault_index_resolves_each_path_once(tmp_path: Path) -> None:
    from obsidian_pdf_exporter.core.vault_index import VaultIndex

    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "Note.md").write_text("x", encoding="utf-8")
    (tmp_path / "link").symlink_to(tmp_path / "real")
    index = VaultIndex(tmp_path)
    folder = tmp_path / "link"
    assert index.resolved(folder) == folder.resolve() == (tmp_path / "real").resolve()
    assert index.resolved(folder) is index.resolved(folder)
    assert index.find_closest_markdown("Note", folder) == tmp_path.resolve() / "real" / "Note.md"


def test_cached_dataview_names_match_the_uncached_functions() -> None:
    from obsidian_pdf_exporter.plugins.dataview.values import canonicalize_var_name
    from obsidian_pdf_exporter.plugins.dataview.values import normalize_header_for_link

    names = ["Due Date", "Due Date", "📅 Termin", "a_b-c  D", "Ü-ber/Straße!", ""]
    for name in names:
        assert canonicalize_var_name(name) == canonicalize_var_name.__wrapped__(name)
        assert normalize_header_for_link(name) == normalize_header_for_link.__wrapped__(name)


def _unlink_reference(html: str, warn: Callable[[str], None] | None = None) -> str:
    """``unlink_missing_targets`` as it was before it left the image data out."""
    ids = set(_RE_ID.findall(html))
    missing = {t for t in _RE_LOCAL_HREF.findall(html) if t not in ids and unquote(t) not in ids}
    if not missing:
        return html
    tree = HtmlTree(html)
    for a in tree.root.xpath("//a[starts-with(@href, '#')]"):
        if a.get("href", "")[1:] in missing:
            unwrap(a)
    for target in sorted(missing):
        if warn is not None:
            warn(outside_message(f"#{unquote(target)}"))
    return tree.serialize()


@pytest.mark.parametrize(
    "body",
    [
        '<p><a href="#nowhere">gone</a> <img src="data:image/png;base64,{red}"></p>',
        '<h1 id="here">H</h1><a href="#here">ok</a><img src="data:image/png;base64,{red}">',
        '<p>Text with <style> as words <a href="#x">x</a></p>'
        '<img src="data:image/png;base64,{red}">',
        '<svg><foreignObject><img src="data:image/png;base64,{red}"/></foreignObject></svg>'
        '<a href="#none">n</a><img src="data:image/jpeg;base64,{red}">',
        "<p>No images, <a href='#none'>a link</a></p>",
    ],
)
def test_unlink_missing_targets_matches_the_reference(body: str) -> None:
    html = f"<html><head></head><body>{body.format(red=_png((255, 0, 0)))}</body></html>"
    warnings: list[str] = []
    reference_warnings: list[str] = []
    assert unlink_missing_targets(html, warnings.append) == _unlink_reference(
        html, reference_warnings.append
    )
    assert warnings == reference_warnings


def test_unlink_missing_targets_keeps_very_long_image_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from obsidian_pdf_exporter.core import html_postprocess

    monkeypatch.setattr(html_postprocess._ImageData, "MAX_DATA", 10)
    red = _png((255, 0, 0))
    html = f'<p><a href="#x">x</a><img src="data:image/png;base64,{red}"></p>'
    assert unlink_missing_targets(html) == _unlink_reference(html)
    assert html_postprocess._ImageData(html).data == []
