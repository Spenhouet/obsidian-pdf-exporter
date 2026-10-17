"""Copy images and other files into the build folder, named by their content.

Pandoc and WeasyPrint read every image from the build folder. A file keeps its
own name there. When a different file of the same name is already in the build
folder, the new one goes into a subfolder named after a hash of its bytes, for
example ``_3f2c9a1b7e/chart.png``.

The name in the build folder therefore depends only on the file name and the
bytes, never on where the file was found. A redline assembles the old and the
new version into one build folder: an image that did not change gets the same
name on both sides, and an image that was replaced by a new file of the same
name gets a different one, so the comparison sees the change.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

DIGEST_CHARS = 10


def content_digest(data: bytes) -> str:
    """A short hash of ``data``, used in file names."""
    return hashlib.sha256(data).hexdigest()[:DIGEST_CHARS]


def stage_bytes(name: str, data: bytes, build_dir: Path) -> str:
    """Write ``data`` as ``name`` into ``build_dir`` and return its path relative to it.

    The file is ``name`` itself unless a file of that name with other bytes is
    already there. Then it is ``_<digest>/name``.
    """
    dest = build_dir / name
    if dest.is_file() and dest.read_bytes() == data:
        return name
    if dest.exists():
        rel = f"_{content_digest(data)}/{name}"
        dest = build_dir / rel
        if dest.is_file():
            return rel
        dest.parent.mkdir(parents=True, exist_ok=True)
    else:
        rel = name
    dest.write_bytes(data)
    return rel


def stage_file(source: Path, build_dir: Path) -> str:
    """Copy ``source`` into ``build_dir`` (see :func:`stage_bytes`) and return its path there."""
    return stage_bytes(source.name, source.read_bytes(), build_dir)
