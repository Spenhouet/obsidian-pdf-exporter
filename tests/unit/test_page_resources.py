"""Tests for the per-page resource dictionaries of the written PDF."""

from __future__ import annotations

import base64
import io
import re
from typing import TYPE_CHECKING

import pydyf
import pypdfium2
from PIL import Image
from pypdf import PdfReader
from weasyprint import HTML

from obsidian_pdf_exporter.core.page_resources import keep_used_page_resources
from obsidian_pdf_exporter.core.pdf import html_to_pdf

if TYPE_CHECKING:
    from pathlib import Path

RE_DRAWN = re.compile(rb"/([^\s/\[\]()<>{}%]+)\s+Do\b")
RE_NAME = re.compile(rb"/([^\s/\[\]()<>{}%]+)")


def _png(color: tuple[int, int, int]) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), color).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _svg(color: str) -> str:
    svg = "<svg xmlns='http://www.w3.org/2000/svg' width='30' height='30'>"
    svg += f"<rect width='30' height='30' fill='{color}' opacity='0.5'/></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode("ascii")


PAGES = [
    f'<p>Red</p><img src="{_png((255, 0, 0))}"><img src="{_svg("green")}">',
    "<p>Only text</p>",
    f'<p>Blue</p><img src="{_png((0, 0, 255))}">',
    '<div style="height:40px;background:linear-gradient(red, blue);opacity:0.4">Fade</div>',
    f'<p>Red again</p><img src="{_png((255, 0, 0))}">',
]
HTML_TEXT = (
    "<html><head><style>section { break-after: page }</style></head><body>"
    + "".join(f"<section>{page}</section>" for page in PAGES)
    + "</body></html>"
)


def _resources(pdf: Path) -> list[dict[str, set[str]]]:
    pages = []
    for page in PdfReader(pdf).pages:
        resources = page["/Resources"]
        pages.append(
            {
                key: {name.lstrip("/") for name in resources[key]}
                for key in ("/XObject", "/ExtGState", "/Pattern", "/Shading", "/Font")
                if key in resources
            }
        )
    return pages


def _pixels(pdf: Path) -> list[bytes]:
    return [page.render(scale=1).to_pil().tobytes() for page in pypdfium2.PdfDocument(str(pdf))]


def test_each_page_lists_only_the_xobjects_it_draws(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    html_to_pdf(HTML_TEXT, out)
    reader = PdfReader(out)
    listed = [set(page["/Resources"].get("/XObject", {})) for page in reader.pages]
    drawn = [
        {"/" + n.decode() for n in RE_DRAWN.findall(page.get_contents().get_data())}
        for page in reader.pages
    ]
    assert listed == drawn


def test_each_page_lists_only_resources_its_content_names(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    html_to_pdf(HTML_TEXT, out)
    reader = PdfReader(out)
    named = [set(RE_NAME.findall(page.get_contents().get_data())) for page in reader.pages]
    listed = [set().union(*page.values()) for page in _resources(out)]
    assert all({n.encode() for n in names} <= named[i] for i, names in enumerate(listed))


def test_pages_look_the_same_as_with_shared_resources(tmp_path: Path) -> None:
    shared, trimmed = tmp_path / "shared.pdf", tmp_path / "trimmed.pdf"
    HTML(string=HTML_TEXT).write_pdf(shared)
    html_to_pdf(HTML_TEXT, trimmed)
    assert _pixels(trimmed) == _pixels(shared)


def test_text_is_the_same_as_with_shared_resources(tmp_path: Path) -> None:
    shared, trimmed = tmp_path / "shared.pdf", tmp_path / "trimmed.pdf"
    HTML(string=HTML_TEXT).write_pdf(shared)
    html_to_pdf(HTML_TEXT, trimmed)
    texts = [[page.extract_text() for page in PdfReader(f).pages] for f in (shared, trimmed)]
    assert texts[0] == texts[1]


def test_same_image_on_two_pages_is_stored_once(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    html_to_pdf(HTML_TEXT, out)
    reader = PdfReader(out)
    first = reader.pages[0]["/Resources"]["/XObject"]
    last = reader.pages[4]["/Resources"]["/XObject"]
    images = {first.raw_get(n).idnum for n in first} & {last.raw_get(n).idnum for n in last}
    assert len(images) == 1


def test_page_with_unexpected_contents_is_left_unchanged() -> None:
    pdf = pydyf.PDF()
    resources = pydyf.Dictionary({"XObject": pydyf.Dictionary({"x0": b"1 0 R"})})
    pdf.add_object(resources)
    page = pydyf.Dictionary({"Type": "/Page", "Resources": resources.reference})
    pdf.add_page(page)
    keep_used_page_resources(None, pdf)
    assert page["Resources"] == resources.reference
