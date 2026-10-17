#!/usr/bin/env python
"""Crop the same scenarios out of several redline PDFs and build a comparison gallery.

    uv run python scripts/redline_gallery.py OUTDIR redline-a.pdf redline-b.pdf ...

Every scenario is found by text: a chain of anchors that leads to the start of
the crop and the text that ends it. A crop that runs over a page break is cut
per page and stacked. Writes ``OUTDIR/crops/<scenario>-<pdf stem>.png`` and
returns the crop paths as JSON on stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

DPI = 150
MM = 72 / 25.4


@dataclass
class Scenario:
    """Where a scenario starts and ends in the PDF."""

    key: str
    title: str
    start: list[str]  # anchors searched one after the other; the last starts the crop
    end: list[str]  # first of these after the start ends the crop (its line is included)
    end_exclusive: bool = False
    body: bool = True  # search after the start of the body only
    top: int = 0  # which start anchor is the top of the crop
    extra: float = 0  # mm added below the end when the last end anchor was used


SCENARIOS = [
    Scenario(
        "summary",
        "Summary block",
        ["Handbook"],
        ["Commits in range"],
        body=False,
        end_exclusive=False,
    ),
    Scenario(
        "words",
        "Word changes in a long paragraph, formatting, link target, footnote",
        ["Purpose", "This handbook describes"],
        ["Records are kept for ten"],
    ),
    Scenario(
        "lists",
        "Nested list: inserted, deleted and reordered items; callouts; tasks",
        ["Review checklist"],
        ["Register entry is updated", "from all sites"],
    ),
    Scenario(
        "tables",
        "Tables: cell edited, row added and deleted, column added",
        ["Record types", "Record"],
        ["Weekly"],
    ),
    Scenario(
        "moves",
        "Moved paragraph (edited) and moved paragraph (unchanged)",
        ["Archiving"],
        ["checked during internal audits"],
    ),
    Scenario(
        "deleted",
        "Long deleted section with headings, Dataview table changed",
        ["Open records", "File"],
        ["accepted as evidence", "Deleted headings"],
        extra=38,
    ),
    Scenario(
        "figures",
        "Replaced image and changed Mermaid diagram",
        ["Storage locations", "Workflow"],
        ["Open records"],
        end_exclusive=True,
        top=1,
    ),
    Scenario(
        "many",
        "A page with 30+ small changes",
        ["Terms and Definitions", "Approval"],
        ["Distribution list"],
    ),
]


def _find(
    doc: pdfium.PdfDocument, text: str, page: int, y: float
) -> tuple[int, float, float] | None:
    """Find ``text`` at or after (page, y from top); return (page, top, bottom) in points."""
    for p in range(page, len(doc)):
        pg = doc[p]
        h = pg.get_size()[1]
        tp = pg.get_textpage()
        s = tp.search(text, match_case=False)
        best = None
        while True:
            r = s.get_next()
            if r is None:
                break
            boxes = [tp.get_charbox(i) for i in range(r[0], r[0] + r[1])]
            top = h - max(b[3] for b in boxes)
            bottom = h - min(b[1] for b in boxes)
            if (p > page or top >= y - 0.5) and (best is None or top < best[1]):
                best = (p, top, bottom)
        if best is not None:
            return best
    return None


def crop(pdf: Path, sc: Scenario, out: Path) -> bool:
    """Write the crop of ``sc`` from ``pdf`` to ``out``; return False when not found."""
    doc = pdfium.PdfDocument(str(pdf))
    page, y = 0, 0.0
    if sc.body:
        hit = _find(doc, "This handbook is the controlled document", 0, 0)
        if hit:
            page, y = hit[0], hit[1]
    start = None
    tops = []
    for anchor in sc.start:
        start = _find(doc, anchor, page, y)
        if start is None:
            return False
        tops.append((start[0], start[1]))
        page, y = start[0], start[2]
    assert start is not None
    end = None
    used_last = False
    for n, cand in enumerate(sc.end):
        e = _find(doc, cand, start[0], start[1])
        if e is not None and e[0] - start[0] <= 2:
            end = e
            used_last = n == len(sc.end) - 1 and n > 0
            break
    if end is None:
        return False
    top_page, top_y = tops[sc.top] if sc.top < len(tops) else (start[0], start[1])
    pad = 5 * MM
    segments = []
    for p in range(top_page, end[0] + 1):
        pg = doc[p]
        w, h = pg.get_size()
        y0 = top_y - pad if p == top_page else 18 * MM
        y1 = end[1] - 3 if sc.end_exclusive else end[2] + 2.5 * MM
        if used_last:
            y1 += sc.extra * MM
        if p != end[0]:
            y1 = h - 20 * MM
        scale = DPI / 72
        img = pg.render(scale=scale).to_pil()
        box = (
            int(6 * MM * scale),
            int(max(0, y0) * scale),
            int((w - 4 * MM) * scale),
            int(min(h, y1) * scale),
        )
        segments.append(img.crop(box))
    width = max(s.width for s in segments)
    gap = 14
    total = sum(s.height for s in segments) + gap * (len(segments) - 1)
    sheet = Image.new("RGB", (width, total), "white")
    yy = 0
    for k, s in enumerate(segments):
        sheet.paste(s, (0, yy))
        yy += s.height
        if k < len(segments) - 1:
            for x in range(0, width, 12):
                for dy in range(gap // 2 - 1, gap // 2 + 1):
                    for dx in range(6):
                        if x + dx < width:
                            sheet.putpixel((x + dx, yy + dy), (150, 150, 150))
            yy += gap
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, optimize=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("outdir", type=Path)
    parser.add_argument("pdfs", nargs="+", type=Path)
    args = parser.parse_args()
    result: dict[str, dict[str, str]] = {}
    for sc in SCENARIOS:
        result[sc.key] = {}
        for pdf in args.pdfs:
            out = args.outdir / "crops" / f"{sc.key}-{pdf.stem}.png"
            if crop(pdf, sc, out):
                result[sc.key][pdf.stem] = str(out.relative_to(args.outdir))
            else:
                print(f"not found: {sc.key} in {pdf.name}", file=sys.stderr)
    json.dump(
        {"scenarios": [(s.key, s.title) for s in SCENARIOS], "crops": result}, sys.stdout, indent=1
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
