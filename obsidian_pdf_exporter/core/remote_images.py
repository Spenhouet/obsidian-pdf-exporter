"""Download the remote images of a document once each, before pandoc runs.

``pandoc --embed-resources`` downloads every remote image it embeds, one
request after the other and again for every place the image is used. A page
that shows the same icon in each row of a table waits for one request per row.

:func:`prefetch_filter` downloads each distinct remote image URL of the
Markdown once, in parallel, and writes a Lua filter that puts the responses
into pandoc's media bag. Pandoc looks a URL up in the media bag before it
downloads it, so it embeds the same bytes with the same MIME type without a
request of its own.

The request is the one pandoc sends: no ``User-Agent`` and
``Accept-Encoding: gzip``. A response is only used when it succeeded, names
a MIME type and is either not encoded or gzip encoded, which is decoded as
pandoc decodes it. Any other URL is left to pandoc, which downloads it as
before.
"""

from __future__ import annotations

import gzip
import html
import http.client
import re
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: Remote image URLs: Markdown images and ``src`` of raw ``<img>`` tags.
RE_MARKDOWN_IMAGE = re.compile(r"!\[[^\]\n]*\]\(\s*<?(https?://[^\s<>()]+)")
RE_IMG_TAG = re.compile(r"<[iI][mM][gG]\b[^>]*?\b[sS][rR][cC]\s*=\s*([\"'])(https?://[^\"'<>]+)\1")

#: Downloads that run at the same time.
THREADS = 8

#: Seconds to wait for a server.
TIMEOUT = 30

#: HTTP status codes of a successful response.
SUCCESS = range(200, 300)

_OPENER = urllib.request.build_opener()
_OPENER.addheaders = []


def remote_image_urls(markdown: str) -> list[str]:
    """The distinct remote image URLs of ``markdown``, in order of first use."""
    urls = [m.group(1) for m in RE_MARKDOWN_IMAGE.finditer(markdown)]
    urls += [html.unescape(m.group(2)) for m in RE_IMG_TAG.finditer(markdown)]
    return list(dict.fromkeys(urls))


def fetch(url: str) -> tuple[str, bytes] | None:
    """Download ``url`` as pandoc does; return its MIME type and bytes, or ``None``."""
    request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})  # noqa: S310 - http(s) only
    try:
        with _OPENER.open(request, timeout=TIMEOUT) as response:
            status = response.status
            mime = response.headers.get("Content-Type")
            encoding = response.headers.get("Content-Encoding")
            body = response.read()
    except (OSError, ValueError, http.client.HTTPException):
        return None
    if status not in SUCCESS or not mime or not mime.isascii():
        return None
    if encoding is not None:
        # Pandoc's HTTP client decodes gzip, except for tar archives.
        if encoding.lower() != "gzip" or mime.lower().startswith("application/x-tar"):
            return None
        try:
            body = gzip.decompress(body)
        except (OSError, EOFError, zlib.error):
            return None
    return mime, body


def prefetch_filter(markdown: str, folder: Path) -> list[str]:
    """Download the remote images of ``markdown``; return the pandoc arguments that use them.

    The responses and the Lua filter are written to ``folder``. Without a
    remote image, or when no download succeeds, the list is empty.
    """
    urls = remote_image_urls(markdown)
    if not urls:
        return []
    with ThreadPoolExecutor(min(THREADS, len(urls))) as pool:
        responses = list(pool.map(fetch, urls))
    lines = [_READ]
    for number, (url, response) in enumerate(zip(urls, responses, strict=True)):
        if response is None:
            continue
        mime, body = response
        path = folder / f"{number}.bin"
        path.write_bytes(body)
        lines.append(f"pandoc.mediabag.insert({_lua(url)}, {_lua(mime)}, read({_lua(str(path))}))")
    if len(lines) == 1:
        return []
    lines.append("return {}")
    script = folder / "remote_images.lua"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ["--lua-filter", str(script)]


_READ = """local function read(path)
  local file = assert(io.open(path, "rb"))
  local data = file:read("a")
  file:close()
  return data
end"""


def _lua(text: str) -> str:
    """A Lua string literal for ``text``, every byte written as a decimal escape."""
    return '"' + "".join(f"\\{byte:03d}" for byte in text.encode()) + '"'
