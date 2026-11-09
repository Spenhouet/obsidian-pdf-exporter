"""Tests for the bounded object streams of the written PDF."""

from __future__ import annotations

import io
from collections import Counter
from typing import TYPE_CHECKING

import pydyf
import pypdfium2
from pypdf import PdfReader
from weasyprint import HTML

from obsidian_pdf_exporter.core.object_streams import OBJECTS_PER_STREAM
from obsidian_pdf_exporter.core.object_streams import bound_object_streams
from obsidian_pdf_exporter.core.object_streams import write_pdf
from obsidian_pdf_exporter.core.page_resources import keep_used_page_resources
from obsidian_pdf_exporter.core.pdf import html_to_pdf

if TYPE_CHECKING:
    from pathlib import Path

# Enough pages, links and outline entries for some hundred objects.
HTML_TEXT = (
    "<html><head><style>section { break-after: page }</style></head><body>"
    + "".join(
        f'<section><h1 id="s{n}">Part {n}</h1><p><a href="#s{(n + 1) % 120}">Next</a></p></section>'
        for n in range(120)
    )
    + "</body></html>"
)


def _stream_sizes(pdf: Path | bytes) -> list[int]:
    """Return the number of objects in each object stream of ``pdf``."""
    data = pdf if isinstance(pdf, bytes) else pdf.read_bytes()
    reader = PdfReader(io.BytesIO(data))
    return list(Counter(stream for stream, _ in reader.xref_objStm.values()).values())


def _pixels(pdf: Path) -> list[bytes]:
    return [page.render(scale=1).to_pil().tobytes() for page in pypdfium2.PdfDocument(str(pdf))]


def _write_unbounded(path: Path) -> None:
    HTML(string=HTML_TEXT).write_pdf(path, finisher=keep_used_page_resources)


def test_object_streams_hold_at_most_the_limit(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    html_to_pdf(HTML_TEXT, out)
    assert max(_stream_sizes(out)) <= OBJECTS_PER_STREAM


def test_all_objects_stay_in_object_streams(tmp_path: Path) -> None:
    unbounded, bounded = tmp_path / "unbounded.pdf", tmp_path / "bounded.pdf"
    _write_unbounded(unbounded)
    html_to_pdf(HTML_TEXT, bounded)
    assert sum(_stream_sizes(bounded)) == sum(_stream_sizes(unbounded)) > OBJECTS_PER_STREAM


def test_pages_look_the_same_as_with_one_object_stream(tmp_path: Path) -> None:
    unbounded, bounded = tmp_path / "unbounded.pdf", tmp_path / "bounded.pdf"
    _write_unbounded(unbounded)
    html_to_pdf(HTML_TEXT, bounded)
    assert _pixels(bounded) == _pixels(unbounded)


def test_text_and_links_are_the_same_as_with_one_object_stream(tmp_path: Path) -> None:
    unbounded, bounded = tmp_path / "unbounded.pdf", tmp_path / "bounded.pdf"
    _write_unbounded(unbounded)
    html_to_pdf(HTML_TEXT, bounded)
    readers = [PdfReader(f) for f in (unbounded, bounded)]
    pages = [
        [(page.extract_text(), len(page.get("/Annots", []))) for page in reader.pages]
        for reader in readers
    ]
    outlines = [len(reader.outline) for reader in readers]
    assert (pages[0], outlines[0]) == (pages[1], outlines[1])


def test_identifier_is_written(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    HTML(string=HTML_TEXT).write_pdf(out, finisher=bound_object_streams, pdf_identifier=b"doc")
    assert PdfReader(out).trailer["/ID"][0] == "doc"


def test_uncompressed_pdf_is_written_by_pydyf() -> None:
    def build() -> pydyf.PDF:
        pdf = pydyf.PDF()
        pdf.add_page(pydyf.Dictionary({"Type": "/Page", "MediaBox": pydyf.Array([0, 0, 10, 10])}))
        return pdf

    own, plain = io.BytesIO(), io.BytesIO()
    write_pdf(build(), own, version=b"1.7", identifier=True, compress=False)
    build().write(plain, version=b"1.7", identifier=True, compress=False)
    assert own.getvalue() == plain.getvalue()
