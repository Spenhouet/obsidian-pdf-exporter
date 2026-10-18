"""Build the small test fonts in ``tests/fixtures/fonts`` from Noto fonts.

The font tests (``tests/unit/test_scripts.py``) export notes in many scripts
with only these fonts installed, so they give the same result on every
machine. Each font is cut down to the characters the test notes use plus a
few common blocks, at the weights the tests need, without hinting.

The Noto fonts come from the Google Fonts repository at a fixed commit. They
are licensed under the SIL Open Font License 1.1; the license of each family
is copied next to the fonts.

Run it after adding characters to the test notes::

    uv run python scripts/build_test_fonts.py
"""

from __future__ import annotations

import argparse
import io
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
OUT = FIXTURES / "fonts"
#: Commit of https://github.com/google/fonts the fonts are taken from.
COMMIT = "47d54ca1ebb14fd864695f1d39dc734f39017c33"
BASE = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl"

LATIN = [
    (0x0020, 0x024F),  # Basic Latin to Latin Extended-B
    (0x0300, 0x036F),  # combining marks
    (0x0370, 0x03FF),  # Greek
    (0x0400, 0x04FF),  # Cyrillic
    (0x2000, 0x206F),  # general punctuation
    (0x20AC, 0x20AC),
    (0x2190, 0x2199),  # arrows
    (0x2212, 0x2212),
    (0x25CC, 0x25CC),  # dotted circle
]

#: (family folder, file, output name, weights, Unicode ranges, take only fixture characters)
FONTS = [
    ("notosans", "NotoSans[wdth,wght].ttf", "NotoSans", (400, 700), LATIN, False),
    (
        "notosansmono",
        "NotoSansMono[wdth,wght].ttf",
        "NotoSansMono",
        (400,),
        [*LATIN, (0x25A0, 0x25FF)],  # list markers such as ◦ and ▪
        False,
    ),
    (
        "notosansarabic",
        "NotoSansArabic[wdth,wght].ttf",
        "NotoSansArabic",
        (400, 700),
        [(0x0600, 0x06FF), (0x0020, 0x0040), (0x25CC, 0x25CC)],
        False,
    ),
    (
        "notosanshebrew",
        "NotoSansHebrew[wdth,wght].ttf",
        "NotoSansHebrew",
        (400, 700),
        [(0x0590, 0x05FF), (0x0020, 0x0040), (0x25CC, 0x25CC)],
        False,
    ),
    (
        "notosansdevanagari",
        "NotoSansDevanagari[wdth,wght].ttf",
        "NotoSansDevanagari",
        (400, 700),
        [(0x0900, 0x097F), (0x0020, 0x0040), (0x200C, 0x200D), (0x25CC, 0x25CC)],
        False,
    ),
    (
        "notosansthai",
        "NotoSansThai[wdth,wght].ttf",
        "NotoSansThai",
        (400, 700),
        [(0x0E00, 0x0E7F), (0x0020, 0x0040), (0x25CC, 0x25CC)],
        False,
    ),
    (
        "notosanssc",
        "NotoSansSC[wght].ttf",
        "NotoSansSC",
        (400, 700),
        [(0x3000, 0x303F), (0x3040, 0x30FF), (0xFF01, 0xFF5E), (0x4E00, 0x9FFF)],
        True,
    ),
    (
        "notoemoji",
        "NotoEmoji[wght].ttf",
        "NotoEmoji",
        (400,),
        [(0x2600, 0x27BF), (0x1F000, 0x1FAFF), (0x200D, 0x200D), (0xFE0F, 0xFE0F)],
        True,
    ),
]


def fixture_characters() -> set[int]:
    """Return every character of the test notes."""
    chars: set[int] = set()
    for folder in ("scripts", "scripts_redline"):
        for path in (FIXTURES / folder).rglob("*.md"):
            chars.update(ord(c) for c in path.read_text(encoding="utf-8"))
            chars.update(ord(c) for c in str(path.relative_to(FIXTURES)))
    return chars


def in_ranges(code: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= code <= end for start, end in ranges)


def download(folder: str, name: str, cache: Path | None) -> bytes:
    if cache is not None and (cache / name).exists():
        return (cache / name).read_bytes()
    url = f"{BASE}/{folder}/{name.replace('[', '%5B').replace(']', '%5D')}"
    with urllib.request.urlopen(url) as response:  # noqa: S310 - fixed https URL
        return response.read()


def build(cache: Path | None, only: list[str]) -> None:
    used = fixture_characters()
    OUT.mkdir(parents=True, exist_ok=True)
    for folder, name, out_name, weights, ranges, only_used in FONTS:
        if only and out_name not in only:
            continue
        for old in OUT.glob(f"{out_name}-*.ttf"):
            old.unlink()
        data = download(folder, name, cache)
        if only_used:
            codes = {c for c in used if in_ranges(c, ranges)} | {0x20, 0x200D, 0xFE0F}
        else:
            codes = {c for start, end in ranges for c in range(start, end + 1)}
        for weight in weights:
            font = TTFont(io.BytesIO(data))
            axes = {axis.axisTag: axis for axis in font["fvar"].axes}
            location = {"wght": weight}
            if "wdth" in axes:
                location["wdth"] = 100
            font = instancer.instantiateVariableFont(font, location, updateFontNames=True)
            options = subset.Options()
            options.layout_features = ["*"]
            options.notdef_outline = True
            options.hinting = False
            # WeasyPrint needs the glyph names to write the text of shaped
            # glyphs (such as joined Arabic letters) into the PDF.
            options.glyph_names = True
            options.name_IDs = ["*"]
            options.name_languages = [0x409]
            subsetter = subset.Subsetter(options)
            subsetter.populate(unicodes=codes)
            subsetter.subset(font)
            style = "Bold" if weight == 700 else "Regular"  # noqa: PLR2004
            font.recalcTimestamp = False  # the same input gives the same file
            font.save(OUT / f"{out_name}-{style}.ttf")
        license_text = download(folder, "OFL.txt", None)
        (OUT / f"{out_name}-OFL.txt").write_bytes(license_text)
    total = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"{len(list(OUT.glob('*.ttf')))} fonts, {total / 1024:.0f} KB in {OUT}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, help="folder with the downloaded variable fonts")
    parser.add_argument("--only", nargs="*", default=[], help="fonts to build, e.g. NotoSans")
    args = parser.parse_args()
    build(args.cache, args.only)


if __name__ == "__main__":
    main()
