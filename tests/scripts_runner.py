"""Export the notes in many scripts and report where their text ends up.

``tests/unit/test_scripts.py`` runs this file in a subprocess with
``FONTCONFIG_FILE`` set, so that each font scenario gets its own fonts (the
font list of a process is fixed once Pango has loaded it).

Usage: ``python tests/scripts_runner.py JOB.json``. The job names the kind
of export (``export``, ``redline`` or ``blame``), its inputs and the file the
report is written to. The report holds, as JSON:

* ``boxes``: every line of text WeasyPrint laid out, with its page, position,
  width and the box it has to stay in.
* ``labels``: every text of every Mermaid diagram, with the width WeasyPrint
  draws, the width Pango measured for the layout and the box it belongs to.
* ``pages``: the text of every PDF page as a PDF reader extracts it, and the
  x position of each character.
* ``outline``: the titles of the PDF bookmarks.
* ``log``: the messages of the export.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SVG = "{http://www.w3.org/2000/svg}"
#: Elements whose text may be cut off on purpose.
CLIPPING = ("hidden", "clip")


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    documents = _capture_documents()
    log: list[str] = []
    output = Path(job["output"])
    if job["kind"] == "redline":
        _redline(job, log)
    else:
        _export(job, log)
    report = {
        "log": log,
        "boxes": [box for document in documents for box in _boxes(document)],
        "labels": _labels(output.parent / f"_build_{output.stem}"),
        "pages": _pages(output),
        "outline": _outline(output),
    }
    Path(job["report"]).write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def _template(job: dict) -> Any:  # noqa: ANN401 - a Template
    from obsidian_pdf_exporter.templates import resolve_template

    return resolve_template(job["template"])


def _export(job: dict, log: list[str]) -> None:
    from obsidian_pdf_exporter.core.exporter import ExportRequest
    from obsidian_pdf_exporter.core.exporter import export_pdf

    request = ExportRequest(
        root=Path(job["root"]),
        output=Path(job["output"]),
        template=_template(job),
        title=job.get("title", ""),
        date="2026-01-02",
        debug=True,
        blame=job["kind"] == "blame",
    )
    export_pdf(request, log=lambda message: log.append(str(message)))


def _redline(job: dict, log: list[str]) -> None:
    from obsidian_pdf_exporter.core.exporter import RedlineRequest
    from obsidian_pdf_exporter.core.exporter import export_redline

    request = RedlineRequest(
        root=Path(job["root"]),
        output=Path(job["output"]),
        template=_template(job),
        from_path=Path(job["from_path"]),
        debug=True,
    )
    export_redline(request, log=lambda message: log.append(str(message)))


def _capture_documents() -> list[Any]:
    """Keep every WeasyPrint document the export lays out (the last one is the PDF)."""
    from obsidian_pdf_exporter.core import diagram_fit
    from obsidian_pdf_exporter.core import pdf

    documents: list[Any] = []
    original = diagram_fit.render_fitted

    def render_fitted(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        document = original(*args, **kwargs)
        documents.append(document)
        return document

    diagram_fit.render_fitted = render_fitted
    pdf.render_fitted = render_fitted
    return documents


# ---- Layout boxes -----------------------------------------------------------


def _boxes(document: Any) -> list[dict]:  # noqa: ANN401 - a WeasyPrint document
    """Return every text box of ``document`` with the box it has to fit in."""
    out: list[dict] = []
    for number, page in enumerate(document.pages, 1):
        page_box = page._page_box
        left = page_box.content_box_x()
        place = {
            "page": number,
            "area": [round(left, 2), round(left + page_box.width, 2)],
            "margin": False,
            "clipped": False,
            "tags": (),
        }
        _walk(page_box, page_box, place, out)
    return out


def _walk(box: Any, container: Any, place: dict, out: list[dict]) -> None:  # noqa: ANN401
    """Add the text boxes inside ``box`` to ``out``.

    ``container`` is the closest block around ``box``, ``place`` says on which
    page and inside which elements ``box`` is.
    """
    from weasyprint.formatting_structure import boxes

    tag = getattr(box, "element_tag", "") or ""
    element = getattr(box, "element", None)
    if element is not None and element.get("class") and tag:
        tag = f"{tag}.{'.'.join(str(element.get('class')).split())}"
    style = getattr(box, "style", None)
    place = {
        **place,
        "margin": place["margin"] or isinstance(box, boxes.MarginBox),
        "clipped": place["clipped"] or (style is not None and style["overflow"] in CLIPPING),
        "tags": (*place["tags"], tag) if tag else place["tags"],
    }
    if isinstance(box, boxes.BlockContainerBox) and not isinstance(box, boxes.LineBox):
        container = box
    if isinstance(box, boxes.TextBox):
        if "::marker" in tag or not box.text.strip():
            return
        left = container.padding_box_x()
        out.append(
            {
                "page": place["page"],
                "text": box.text,
                "x0": round(box.position_x, 2),
                "x1": round(box.position_x + box.width, 2),
                "y": round(box.position_y, 2),
                "box": [round(left, 2), round(left + container.padding_width(), 2)],
                "area": place["area"],
                "margin": place["margin"],
                "clipped": place["clipped"],
                "tags": list(place["tags"]),
                "dir": box.style["direction"],
                "classes": _classes(container),
            }
        )
        return
    for child in getattr(box, "children", None) or ():
        _walk(child, container, place, out)


def _classes(box: Any) -> str:  # noqa: ANN401
    element = getattr(box, "element", None)
    return str(element.get("class") or "") if element is not None else ""


# ---- Mermaid labels ---------------------------------------------------------


def _labels(build_dir: Path) -> list[dict]:
    """Return the drawn and the measured width of every text of every diagram."""
    if not build_dir.is_dir():
        return []
    from obsidian_pdf_exporter.core import mermaid_pele

    out: list[dict] = []
    for path in sorted(build_dir.glob("mermaid-*.svg")):
        svg = path.read_text(encoding="utf-8")
        root = ET.fromstring(svg)  # noqa: S314 - an SVG written by the export
        theme = mermaid_pele.PeleTheme(font_family=root.get("font-family", "sans-serif"))
        measurer = mermaid_pele._PangoMeasurer(theme)
        out.extend(_diagram_labels(path.name, svg, root, measurer))
    return out


def _diagram_labels(name: str, svg: str, root: ET.Element, measurer: Any) -> list[dict]:  # noqa: ANN401
    drawn = _draw(svg)
    view_box = [float(v) for v in root.get("viewBox", "0 0 0 0").split()]
    rects: list[tuple[float, float, float, float]] = []
    texts: list[tuple[ET.Element, list[ET.Element], dict[str, str]]] = []

    def walk(element: ET.Element, chain: list[ET.Element], inherited: dict[str, str]) -> None:
        values = dict(inherited)
        for attribute in ("font-size", "text-anchor", "font-weight"):
            if element.get(attribute):
                values[attribute] = str(element.get(attribute))
        chain = [*chain, element]
        tag = element.tag.replace(SVG, "")
        if tag == "rect":
            dx, dy = _translation(chain)
            rects.append(
                (
                    float(element.get("x", 0)) + dx,
                    float(element.get("y", 0)) + dy,
                    float(element.get("width", 0)),
                    float(element.get("height", 0)),
                )
            )
        if tag in ("text", "tspan"):
            texts.append((element, chain, values))
        for child in element:
            walk(child, chain, values)

    walk(root, [], {"font-size": root.get("font-size", "16")})
    if len(texts) != len(drawn):
        return [{"diagram": name, "error": f"{len(texts)} texts, {len(drawn)} drawn"}]
    out = []
    for (element, chain, values), (text, width) in zip(texts, drawn, strict=True):
        if not text.strip():
            continue
        dx, dy = _translation(chain)
        x = float((element.get("x") or "0").split()[0]) + dx
        y = float((element.get("y") or "0").split()[0]) + dy
        size = float(values["font-size"])
        align = {"middle": 0.5, "end": 1.0}.get(values.get("text-anchor", "start"), 0.0)
        left = x - width * align
        middle = y - size * 0.35
        inside = [
            r
            for r in rects
            if r[0] - 1 <= x <= r[0] + r[2] + 1 and r[1] - 1 <= middle <= r[1] + r[3] + 1
        ]
        box = min(inside, key=lambda r: r[2] * r[3]) if inside else tuple(view_box)
        style = 1 if values.get("font-weight") in ("bold", "700") else 0
        key = f"{style}|{size:g}|{text}"
        out.append(
            {
                "diagram": name,
                "text": text,
                "drawn": round(width, 2),
                "measured": round(measurer.widths([key])[key], 2),
                "x0": round(left, 2),
                "x1": round(left + width, 2),
                "box": [round(box[0], 2), round(box[0] + box[2], 2)],
                "in_rect": bool(inside),
            }
        )
    return out


def _draw(svg: str) -> list[tuple[str, float]]:
    """Draw ``svg`` with WeasyPrint and return each text with the width WeasyPrint gave it."""
    import weasyprint
    import weasyprint.svg as weasy_svg

    drawn: list[tuple[str, float]] = []
    original = weasy_svg.TAGS["text"]

    def text(svg_obj: Any, node: Any, font_size: float) -> Any:  # noqa: ANN401
        result = original(svg_obj, node, font_size)
        box = node.text_bounding_box
        width = box[2] if node.text and box[2] not in (float("inf"), float("-inf")) else 0.0
        drawn.append((node.text or "", width))
        return result

    saved = dict(weasy_svg.TAGS)
    for tag, function in saved.items():
        if function is original:
            weasy_svg.TAGS[tag] = text
    saved_text = weasy_svg.text
    weasy_svg.text = text
    try:
        weasyprint.HTML(string=f"<body style='margin:0'>{svg}</body>").write_pdf()
    finally:
        weasy_svg.TAGS.clear()
        weasy_svg.TAGS.update(saved)
        weasy_svg.text = saved_text
    return drawn


def _translation(chain: list[ET.Element]) -> tuple[float, float]:
    dx = dy = 0.0
    for element in chain:
        transform = element.get("transform")
        if not transform:
            continue
        m = re.fullmatch(r"\s*translate\(\s*([-\d.e]+)[\s,]*([-\d.e]*)\s*\)\s*", transform)
        if not m:
            msg = f"transform not supported: {transform}"
            raise ValueError(msg)
        dx += float(m.group(1))
        dy += float(m.group(2) or 0)
    return dx, dy


# ---- PDF ----------------------------------------------------------------------


def _pages(output: Path) -> list[dict]:
    """Return the text of every page and the x position of every character."""
    import pypdfium2

    pdf = pypdfium2.PdfDocument(output)
    out = []
    try:
        for page in pdf:
            text_page = page.get_textpage()
            count = text_page.count_chars()
            text = text_page.get_text_range(0, count)
            xs = [round(text_page.get_charbox(i)[0], 2) for i in range(count)]
            out.append({"text": text, "x": xs, "width": page.get_width()})
    finally:
        pdf.close()
    return out


def _outline(output: Path) -> list[str]:
    import pypdfium2

    pdf = pypdfium2.PdfDocument(output)
    try:
        return [
            item.get_title() if hasattr(item, "get_title") else item.title for item in pdf.get_toc()
        ]
    finally:
        pdf.close()


if __name__ == "__main__":
    main()
