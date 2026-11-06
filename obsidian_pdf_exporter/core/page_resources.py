"""Give every PDF page a resource dictionary with only the resources it draws.

WeasyPrint writes one resource dictionary for the whole document and points every
page at it. Each image, SVG drawing, transparency group, pattern and shading of the
document gets an entry in that dictionary, so every page lists all of them. A PDF
viewer reads the resources of each page it shows. With some thousand images and
drawings in a long document, browser viewers open the file slowly and scroll with
lag.

:func:`keep_used_page_resources` is a WeasyPrint finisher. It runs on the
:class:`pydyf.PDF` right before it is written, reads the names that the content
stream of each page uses, and gives the page its own resource dictionary with only
those entries. The objects themselves are not touched, so the pages draw the same.

Upstream issue: https://github.com/Kozea/WeasyPrint/issues/3013
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pydyf

# Resource types whose entries a content stream calls by name.
NAMED_RESOURCES = ("ExtGState", "XObject", "Pattern", "Shading", "Font", "Properties")

# A PDF name token: "/" and the characters up to the next delimiter or white space.
RE_NAME = re.compile(rb"/([^\s/\[\]()<>{}%]+)")

# A reference as pydyf writes it, "12 0 R".
RE_REFERENCE = re.compile(rb"(\d+) (\d+) R")


def keep_used_page_resources(_document: object, pdf: pydyf.PDF) -> None:
    """Replace the resources of each page of ``pdf`` with the ones its content uses.

    Entries of :data:`NAMED_RESOURCES` that the content stream of the page does not
    name are left out. Other entries, such as the color spaces, are kept as they
    are. A page whose resources or contents are not of the expected form is left
    unchanged. The signature is that of a WeasyPrint ``finisher``.
    """
    import pydyf

    objects = pdf.objects
    # ``Kids`` holds "number 0 R" as three items per page.
    for number in pdf.pages["Kids"][::3]:
        page = objects[number]
        resources = _resolve(objects, page.get("Resources"))
        contents = _resolve(objects, page.get("Contents"))
        if not isinstance(resources, dict) or not isinstance(contents, pydyf.Stream):
            continue
        names = used_names(contents)
        own = pydyf.Dictionary()
        for key, value in resources.items():
            entries = _resolve(objects, value) if key in NAMED_RESOURCES else None
            if not isinstance(entries, dict):
                own[key] = value
                continue
            used = {name: entry for name, entry in entries.items() if name in names}
            if used:
                own[key] = pydyf.Dictionary(used)
        page["Resources"] = own


def used_names(stream: pydyf.Stream) -> set[str]:
    """Return every name that the content of ``stream`` contains, without the slash.

    The scan does not parse operators, so names that are not resources (or text in
    a literal string that looks like a name) are included too. That only means a
    resource may be kept that the page does not draw, never that one is dropped.
    """
    names: set[str] = set()
    for item in stream.stream:
        names.update(m.decode("latin-1") for m in RE_NAME.findall(_item_bytes(item)))
    return names


def _item_bytes(item: object) -> bytes:
    """Return a content stream item as pydyf writes it."""
    if isinstance(item, bytes):
        return item
    data = getattr(item, "data", None)
    if isinstance(data, bytes):
        return data
    return str(item).encode("latin-1", errors="replace")


def _resolve(objects: list[pydyf.Object], value: object) -> object:
    """Return the object that ``value`` refers to, or ``value`` if it is no reference."""
    if isinstance(value, bytes):
        match = RE_REFERENCE.fullmatch(value)
        if match and int(match.group(1)) < len(objects):
            return objects[int(match.group(1))]
    return value
