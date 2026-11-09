"""Write the PDF with object streams of at most :data:`OBJECTS_PER_STREAM` objects.

With compression on, pydyf puts every object that is not a stream into one single
object stream: all pages, annotations, outline entries, fonts and image dictionaries.
In a document with some thousand pages that is one stream with ten thousands of
objects and some megabytes of data. A viewer that resolves objects through object
streams without caching them reads that one large stream again and again, and opens
and scrolls the document slowly. Microsoft Edge's built-in viewer is one of them.

:func:`bound_object_streams` is a WeasyPrint finisher. It makes the
:class:`pydyf.PDF` write the same objects into object streams of at most
:data:`OBJECTS_PER_STREAM` objects each, the default of qpdf. Everything else is
written as pydyf writes it, so the pages draw the same.

Upstream issue: https://github.com/CourtBouillon/pydyf/issues/39
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from hashlib import md5
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO

    import pydyf

# The most objects in one object stream, as qpdf writes them.
OBJECTS_PER_STREAM = 100


@dataclass
class WriteOptions:
    """The options of :meth:`pydyf.PDF.write` after ``output``, with its defaults."""

    version: bytes | str | None = b"1.7"
    identifier: bytes | str | bool | None = False
    compress: bool = False


def bound_object_streams(_document: object, pdf: pydyf.PDF) -> None:
    """Make ``pdf`` write object streams of at most :data:`OBJECTS_PER_STREAM` objects.

    The signature is that of a WeasyPrint ``finisher``. WeasyPrint calls
    ``pdf.write`` right after the finisher, which then runs :func:`write_pdf`.
    """
    pdf.write = functools.partial(write_pdf, pdf)


def write_pdf(pdf: pydyf.PDF, output: BinaryIO, *args: object, **kwargs: object) -> None:
    """Write ``pdf`` to ``output`` as :meth:`pydyf.PDF.write` does.

    ``args`` and ``kwargs`` are those of :meth:`pydyf.PDF.write`, see
    :class:`WriteOptions`. With ``compress`` and a PDF version of 1.5 or later, the
    objects pydyf would put into its one object stream go into object streams of at
    most :data:`OBJECTS_PER_STREAM` objects, in the order of their numbers. Otherwise
    :meth:`pydyf.PDF.write` writes the PDF.
    """
    import pydyf

    options = WriteOptions(*args, **kwargs)
    version = _bytes(options.version or b"1.7")
    if not options.compress or version < b"1.5":
        pydyf.PDF.write(pdf, output, version, options.identifier, options.compress)
        return

    if pdf.info:
        pdf.add_object(pdf.info)
    pdf.write_line(b"%PDF-" + version, output)
    pdf.write_line(b"%\xf0\x9f\x96\xa4", output)
    places = _write_objects(pdf, output)
    xref_stream = _xref_stream(pdf, places, options)
    pdf.xref_position = xref_stream.offset = pdf.current_position
    pdf.add_object(xref_stream)
    pdf.write_line(xref_stream.indirect, output)
    pdf.write_line(b"startxref", output)
    pdf.write_line(f"{pdf.xref_position}".encode(), output)
    pdf.write_line(b"%%EOF", output)


def _write_objects(pdf: pydyf.PDF, output: BinaryIO) -> dict[int, tuple[int, int]]:
    """Write the objects of ``pdf`` and return where the packed ones are.

    Objects that cannot go into an object stream are written as they are, the others
    go into object streams of at most :data:`OBJECTS_PER_STREAM` objects. The result
    maps the number of each packed object to the number of its object stream and its
    index in that stream.
    """
    packed = []
    for object_ in pdf.objects:
        if object_.free == "f":
            continue
        if object_.compressible:
            packed.append(object_)
        else:
            object_.offset = pdf.current_position
            pdf.write_line(object_.indirect, output)

    places: dict[int, tuple[int, int]] = {}
    for start in range(0, len(packed), OBJECTS_PER_STREAM):
        chunk = packed[start : start + OBJECTS_PER_STREAM]
        stream = _object_stream(chunk)
        stream.offset = pdf.current_position
        pdf.add_object(stream)
        pdf.write_line(stream.indirect, output)
        for index, object_ in enumerate(chunk):
            places[object_.number] = (stream.number, index)
    return places


def _object_stream(objects: list[pydyf.Object]) -> pydyf.Stream:
    """Return a compressed object stream (``/Type /ObjStm``) holding ``objects``."""
    import pydyf

    header = []
    items: list[bytes] = []
    position = 0
    for object_ in objects:
        data = object_.data
        header += [object_.number, position]
        items.append(data)
        position += len(data) + 1
    first = " ".join(str(value) for value in header).encode("ascii")
    extra = {"Type": "/ObjStm", "N": len(objects), "First": len(first) + 1}
    return pydyf.Stream([first, *items], extra, compress=True)


def _xref_stream(
    pdf: pydyf.PDF,
    places: dict[int, tuple[int, int]],
    options: WriteOptions,
) -> pydyf.Stream:
    """Return the cross-reference stream of ``pdf``, which is written next.

    ``places`` is the result of :func:`_write_objects`. The stream gets the last
    entry, at the current position.
    """
    import pydyf

    identifier = options.identifier
    xref = []
    for object_ in pdf.objects:
        if object_.number in places:
            xref.append((2, *places[object_.number]))
        elif object_.free == "f":
            xref.append((0, 0, object_.generation))
        else:
            xref.append((1, object_.offset, object_.generation))
    xref.append((1, pdf.current_position, 0))
    widths = (
        1,
        _width(max(pdf.current_position, len(pdf.objects))),
        _width(max(object_.generation for object_ in pdf.objects)),
    )
    data = b"".join(
        value.to_bytes(width, "big")
        for line in xref
        for width, value in zip(widths, line, strict=True)
    )
    extra = {
        "Type": "/XRef",
        "Index": pydyf.Array((0, len(pdf.objects) + 1)),
        "W": pydyf.Array(widths),
        "Size": len(pdf.objects) + 1,
        "Root": pdf.catalog.reference,
    }
    if pdf.info:
        extra["Info"] = pdf.info.reference
    if identifier:
        # The file ID as pydyf writes it, from the data of all written objects.
        written = b"".join(object_.data for object_ in pdf.objects if object_.free != "f")
        data_hash = md5(written, usedforsecurity=False).hexdigest().encode()
        first = data_hash if identifier is True else _bytes(identifier)
        extra["ID"] = pydyf.Array((pydyf.String(first).data, pydyf.String(data_hash).data))
    return pydyf.Stream([data], extra, compress=True)


def _width(value: int) -> int:
    """Return the number of bytes needed to write ``value``, at least one."""
    return max(1, (value.bit_length() + 7) // 8)


def _bytes(value: bytes | str) -> bytes:
    """Return ``value`` as bytes."""
    return value if isinstance(value, bytes) else str(value).encode("ascii")
