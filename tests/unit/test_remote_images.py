"""Tests for downloading remote images once before pandoc runs."""

from __future__ import annotations

import gzip
import shutil
import threading
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING
from typing import ClassVar

import pytest

from obsidian_pdf_exporter.core import pandoc
from obsidian_pdf_exporter.core import remote_images
from obsidian_pdf_exporter.core.pandoc import render_html

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4">'
    b'<rect width="4" height="4"/></svg>'
)
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c63f8cfc0f01f0005000201a5f6b7c90000000049454e44ae426082"
)

#: Path -> (status, headers, body) the test server answers with.
ROUTES: dict[str, tuple[int, dict[str, str], bytes]] = {
    "/icon.svg": (200, {"Content-Type": "image/svg+xml;charset=UTF-8"}, SVG),
    "/zipped?size=medium": (
        200,
        {"Content-Type": "image/svg+xml", "Content-Encoding": "gzip"},
        gzip.compress(SVG),
    ),
    "/dot.png": (200, {"Content-Type": "image/png"}, PNG),
    "/typeless.png": (200, {}, PNG),
    "/brotli.svg": (200, {"Content-Type": "image/svg+xml", "Content-Encoding": "br"}, b"x"),
    "/missing.png": (404, {"Content-Type": "text/html"}, b"<p>not found</p>"),
}


class _Handler(BaseHTTPRequestHandler):
    requests: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        self.requests.append(self.path)
        status, headers, body = ROUTES.get(self.path, (404, {}, b""))
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - name of the base method
        pass


@pytest.fixture
def server() -> Iterator[str]:
    """A local HTTP server for ``ROUTES``; yields its base URL."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _Handler.requests = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_remote_image_urls_finds_markdown_images_and_img_tags() -> None:
    markdown = (
        '![a](https://x.test/a.png) ![b](<https://x.test/b.png> "t") ![a](https://x.test/a.png)\n'
        '<img alt="c" SRC="https://x.test/c.png?a=1&amp;b=2"> [link](https://x.test/d.png)\n'
        '![local](pic.png) <script src="https://x.test/e.js"></script>'
    )
    assert remote_images.remote_image_urls(markdown) == [
        "https://x.test/a.png",
        "https://x.test/b.png",
        "https://x.test/c.png?a=1&b=2",
    ]


def test_fetch_decodes_gzip_and_keeps_the_mime_type(server: str) -> None:
    assert remote_images.fetch(f"{server}/zipped?size=medium") == ("image/svg+xml", SVG)
    assert remote_images.fetch(f"{server}/icon.svg") == ("image/svg+xml;charset=UTF-8", SVG)


@pytest.mark.parametrize("path", ["/typeless.png", "/brotli.svg", "/missing.png"])
def test_fetch_leaves_other_responses_to_pandoc(server: str, path: str) -> None:
    assert remote_images.fetch(f"{server}{path}") is None


def test_fetch_of_an_unreachable_server_gives_none() -> None:
    assert remote_images.fetch("http://127.0.0.1:9/x.png") is None


def test_without_remote_images_pandoc_gets_no_filter(tmp_path: Path) -> None:
    assert remote_images.prefetch_filter("![a](a.png)", tmp_path) == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_prefetched_images_give_the_html_of_pandoc_downloading_them(
    tmp_path: Path, server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each URL is requested once, and the HTML is the one pandoc writes when it downloads."""
    names = ["icon.svg", "zipped?size=medium", "dot.png", "typeless.png", "missing.png"]
    rows = "\n".join(f"| ![{n}]({server}/{n}) | {k} |" for k in range(3) for n in names)
    markdown = f'| a | b |\n|---|---|\n{rows}\n\n<img src="{server}/dot.png" alt="x">\n'

    html = render_html(markdown, "x.css", "T", tmp_path, toc=False)
    prefetched = sorted(_Handler.requests)

    _Handler.requests = []
    monkeypatch.setattr(pandoc, "prefetch_filter", lambda _markdown, _folder: [])
    reference = render_html(markdown, "x.css", "T", tmp_path, toc=False)

    assert html == reference
    assert "data:image/svg+xml;charset=UTF-8;base64," in html
    assert sorted(_Handler.requests).count("/dot.png") == 4
    # Pandoc still downloads what was not handed over, as before.
    assert prefetched == sorted(
        ["/icon.svg", "/zipped?size=medium", "/dot.png"]
        + ["/typeless.png"] * 4
        + ["/missing.png"] * 4
    )
