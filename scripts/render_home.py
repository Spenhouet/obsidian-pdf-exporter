#!/usr/bin/env python
"""Render the images of the docs home page.

The home page shows a small handbook vault (``examples/_showcase/Handbook``)
exported to PDF, and thumbnails of the feature, template and Redline
screenshots. Everything goes to ``docs/img/home/`` as WebP with fixed sizes,
so the ``width`` and ``height`` attributes in ``docs/index.md`` stay right:

- ``handbook-<n>.webp``: the pages of the exported handbook, 840 x 1188.
- ``<feature>.webp``: the top of ``docs/img/features/<feature>.png``,
  720 x 450, for the cards.
- ``template-<recipe>.webp``: ``docs/img/templates/<recipe>.png`` as WebP.

The Redline section uses ``docs/img/redline/*.png`` as they are: those
screenshots are smaller as PNG than as WebP.

The thumbnails are made from the committed screenshots, so run
``render_examples.py`` and ``render_redline_examples.py`` first when their
output changed. Run from the repository root:

    uv run python scripts/render_home.py

Needs ``pdftoppm`` (poppler) and Node.js for the Mermaid diagram.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from PIL import ImageChops

from obsidian_pdf_exporter.main import app

REPO = Path(__file__).resolve().parent.parent
IMG = REPO / "docs" / "img"
OUT = IMG / "home"
SHOWCASE = REPO / "examples" / "_showcase" / "Handbook"

PAGE_SIZE = (840, 1188)  # A4 at about 2x the size the page is shown at
CARD_SIZE = (720, 450)  # 16:10, about 2x the size of a card image
CARD_PADDING = 16  # white kept around the content of a card image, in pixels
MAX_ZOOM = 1.6  # largest scale-up of a short screenshot
QUALITY = 82

#: Card thumbnails: feature screenshots in docs/img/features.
FEATURES = (
    "folder-notes",
    "callouts",
    "embed-notes",
    "mermaid",
    "tables",
    "wiki-links",
    "dataview",
    "bases",
    "excalidraw",
    "drawio",
    "citations",
    "math",
)

#: Whole pages of the template recipes in docs/img/templates.
TEMPLATES = ("default", "letterhead", "confidential", "dark")


def main() -> None:
    if shutil.which("pdftoppm") is None:
        sys.exit("pdftoppm not found; install poppler-utils")
    OUT.mkdir(parents=True, exist_ok=True)
    render_handbook()
    for name in FEATURES:
        card(IMG / "features" / f"{name}.png", OUT / f"{name}.webp")
    for name in TEMPLATES:
        save(Image.open(IMG / "templates" / f"{name}.png").convert("RGB"), f"template-{name}")


def render_handbook() -> None:
    """Export the showcase handbook and write every page."""
    with tempfile.TemporaryDirectory(prefix="ope-home-") as tmp:
        pdf = Path(tmp) / "handbook.pdf"
        args = ["export", str(SHOWCASE), "-o", str(pdf), "--title", "Team handbook"]
        args += ["--version", "1.2.0", "--date", "2026-04-01"]
        print("ope", " ".join(args), flush=True)
        app(args, standalone_mode=False)
        prefix = Path(tmp) / "page"
        subprocess.run(["pdftoppm", "-r", "200", "-png", str(pdf), str(prefix)], check=True)
        pages = sorted(Path(tmp).glob("page-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        for old in OUT.glob("handbook-*.webp"):
            old.unlink()
        for n, page in enumerate(pages, start=1):
            image = Image.open(page).convert("RGB")
            save(image.resize(PAGE_SIZE, Image.Resampling.LANCZOS), f"handbook-{n}")


def card(source: Path, target: Path) -> None:
    """Fit a screenshot into a card image on white paper.

    The white margin around the content is cut off first. A tall screenshot
    is scaled to the card width and keeps its top; a short one is centered
    and scaled up at most ``MAX_ZOOM`` times, so small examples stay legible.
    """
    image = Image.open(source).convert("RGB")
    box = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
    if box is not None:
        image = image.crop(
            (
                max(box[0] - CARD_PADDING, 0),
                max(box[1] - CARD_PADDING, 0),
                min(box[2] + CARD_PADDING, image.width),
                min(box[3] + CARD_PADDING, image.height),
            )
        )
    width, height = CARD_SIZE
    scale = width / image.width
    if image.height * scale < height:
        scale = min(scale, height / image.height, MAX_ZOOM)
    size = (round(image.width * scale), round(image.height * scale))
    scaled = image.resize(size, Image.Resampling.LANCZOS)
    out = Image.new("RGB", CARD_SIZE, "white")
    if scaled.height >= height:
        out.paste(scaled.crop((0, 0, min(width, scaled.width), height)), (0, 0))
    else:
        out.paste(scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2))
    save(out, target.stem)


def save(image: Image.Image, stem: str) -> None:
    path = OUT / f"{stem}.webp"
    image.save(path, "WEBP", quality=QUALITY, method=6)
    size = path.stat().st_size // 1024
    print(f"  wrote {path.relative_to(REPO)} ({image.width}x{image.height}, {size} KB)", flush=True)


if __name__ == "__main__":
    main()
