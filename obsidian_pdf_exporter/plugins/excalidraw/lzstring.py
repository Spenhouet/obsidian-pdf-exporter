"""Decompress LZ-String ``compressToBase64`` output.

The Excalidraw plugin stores the scene of a drawing as
``LZString.compressToBase64(json)`` in a ```` ```compressed-json ```` block,
split into lines. This is a port of ``decompressFromBase64`` from
`lz-string <https://github.com/pieroxy/lz-string>`_ (MIT), version 1.5.
"""

from __future__ import annotations

_BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
_BASE64_VALUES = {ch: i for i, ch in enumerate(_BASE64)}


class _Bits:
    """Reads the bit stream of the compressed data, ``reset`` bits per character."""

    def __init__(self, values: list[int], reset: int) -> None:
        self.values = values
        self.reset = reset
        self.val = values[0] if values else 0
        self.position = reset
        self.index = 1

    def read(self, count: int) -> int:
        bits = 0
        power = 1
        for _ in range(count):
            resb = self.val & self.position
            self.position >>= 1
            if self.position == 0:
                self.position = self.reset
                self.val = self.values[self.index] if self.index < len(self.values) else 0
                self.index += 1
            if resb:
                bits |= power
            power <<= 1
        return bits


def decompress_from_base64(data: str) -> str | None:
    """Return the text that ``LZString.compressToBase64`` turned into ``data``.

    Whitespace in ``data`` is ignored, so the line-wrapped blocks of the
    Excalidraw plugin can be passed as they are. Returns None for data that
    is not valid LZ-String output.
    """
    compact = "".join(data.split())
    if not compact:
        return None
    values = [_BASE64_VALUES.get(ch, 0) for ch in compact]
    units = _decompress(values, 32)
    if units is None:
        return None
    # The JavaScript original works on UTF-16 code units, so characters
    # outside the BMP arrive as surrogate pairs.
    text = "".join(units)
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _decompress(values: list[int], reset: int) -> list[str] | None:  # noqa: C901 - one algorithm
    dictionary: list[str] = ["", "", ""]
    enlarge_in = 4
    num_bits = 3
    bits = _Bits(values, reset)

    first = bits.read(2)
    if first == 0:
        c = chr(bits.read(8))
    elif first == 1:
        c = chr(bits.read(16))
    else:
        return []
    dictionary.append(c)
    w = c
    result = [c]

    while True:
        if bits.index > len(values):
            return None
        code = bits.read(num_bits)
        if code in (0, 1):
            dictionary.append(chr(bits.read(8 if code == 0 else 16)))
            code = len(dictionary) - 1
            enlarge_in -= 1
        elif code == 2:  # noqa: PLR2004 - end of stream marker
            return result
        if enlarge_in == 0:
            enlarge_in = 2**num_bits
            num_bits += 1
        if code < len(dictionary):
            entry = dictionary[code]
        elif code == len(dictionary):
            entry = w + w[0]
        else:
            return None
        result.append(entry)
        dictionary.append(w + entry[0])
        enlarge_in -= 1
        w = entry
        if enlarge_in == 0:
            enlarge_in = 2**num_bits
            num_bits += 1
