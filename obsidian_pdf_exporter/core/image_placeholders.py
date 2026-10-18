"""Let pandoc embed a short placeholder for each raster image of the build folder.

``pandoc --embed-resources`` writes every image into the HTML as base64. For a
folder with many screenshots, that is most of the HTML: pandoc takes long to
write it, every later step has to carry it, and WeasyPrint needs the images as
files again (see :func:`obsidian_pdf_exporter.core.pdf.images_to_files`).

:class:`ImagePlaceholders` writes a placeholder for every raster image of the
build folder into a folder next to it, under the same relative path. Each
placeholder holds a short unique text. Pandoc runs with that folder first on
its resource path, so it embeds the placeholders and finds every other file as
before. Pandoc takes the MIME type of an image from its file name, so the
``data:`` URL is the same apart from the data.

Afterwards :meth:`ImagePlaceholders.with_data` puts the real data back, which
gives the same HTML as embedding the images, and
:meth:`ImagePlaceholders.with_files` points each image at its file instead.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType

#: File name endings of the images that get a placeholder.
RASTER_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"})

_URL_QUOTES = str.maketrans({"(": "%28", ")": "%29", "'": "%27"})


class ImagePlaceholders:
    """Placeholders for the raster images of ``build_dir``, for one pandoc run.

    Use it as a context manager around the pandoc run: the placeholder folder
    is removed on exit. The methods that put the images back work afterwards.
    """

    def __init__(self, build_dir: Path) -> None:
        # Next to the build folder, so a path with ".." leads to the same file.
        self.folder = Path(
            tempfile.mkdtemp(prefix=f"{build_dir.name}-images-", dir=build_dir.parent)
        )
        # 18 + 9 characters: a multiple of 3, so the base64 has no padding.
        prefix = f"ope-image-{secrets.token_hex(4)}"
        self.files: list[Path] = []
        for path in sorted(build_dir.rglob("*")):
            if path.suffix.lower() not in RASTER_SUFFIXES or not path.is_file():
                continue
            placeholder = self.folder / path.relative_to(build_dir)
            placeholder.parent.mkdir(parents=True, exist_ok=True)
            placeholder.write_bytes(f"{prefix}{len(self.files):09d}".encode())
            self.files.append(path)
        encoded = base64.b64encode(prefix.encode()).decode()
        self._data_url = re.compile(
            rf"data:[^;,\"'\s]+;base64,(?P<key>{re.escape(encoded)}[A-Za-z0-9+/]{{12}})"
        )

    def __enter__(self) -> ImagePlaceholders:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    def _file(self, key: str) -> Path:
        return self.files[int(base64.b64decode(key)[-9:])]

    def with_data(self, html: str) -> str:
        """Return ``html`` with the image data in place of each placeholder."""
        if not self.files:
            return html

        def replace(m: re.Match[str]) -> str:
            data = base64.b64encode(self._file(m.group("key")).read_bytes()).decode("ascii")
            return m.group(0).replace(m.group("key"), data)

        return self._data_url.sub(replace, html)

    def with_files(self, html: str) -> str:
        """Return ``html`` with a ``file:`` URL in place of each placeholder ``data:`` URL.

        Images with the same bytes get the URL of the same file, so WeasyPrint
        reads them once and puts them into the PDF once.
        """
        if not self.files:
            return html
        urls: dict[Path, str] = {}
        by_content: dict[str, str] = {}

        def replace(m: re.Match[str]) -> str:
            path = self._file(m.group("key"))
            if path not in urls:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                # Quoted so the URL also works unquoted in a CSS ``url()``.
                uri = path.resolve().as_uri().translate(_URL_QUOTES)
                urls[path] = by_content.setdefault(digest, uri)
            return urls[path]

        return self._data_url.sub(replace, html)
