r"""Render LaTeX math (``$...$`` and ``$$...$$``) to inline SVG.

WeasyPrint has no MathML or MathJax support. Pandoc writes math as MathML
(``--mathml``), with the TeX source kept in an ``<annotation>``. Each
``<math>`` element is rendered with `ziamath`, a pure-Python renderer that
needs no TeX installation, and replaced by an ``<svg>`` sized in ``em`` so it
scales with the surrounding text. Formulas that fail to render stay as
code-styled source and a warning is logged. So do formulas with characters
the math font has no glyph for, such as Chinese in ``\text{}``: ziamath
draws every character in its math font, they would come out as empty boxes.
"""

from __future__ import annotations

import html as html_lib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_MATH = re.compile(r"<math\b([^>]*)>(.*?)</math>", re.DOTALL)
_ANNOTATION = re.compile(
    r'<annotation encoding="application/x-tex">(.*?)</annotation>',
    re.DOTALL,
)
_SIZE = 16.0
_SVG_ROOT = re.compile(r"<svg\b[^>]*>")


def render_math(html: str, log: Callable[[str], None] = print) -> str:
    """Replace the MathML ``<math>`` elements in ``html`` with inline SVG."""
    if "<math" not in html:
        return html
    try:
        import ziafont
        import ziamath
    except ImportError:
        log("  Warning: ziamath is not installed, math is shown as source")
        return _MATH.sub(lambda m: _fallback(m.group(1), m.group(2)), html)

    previous = (ziafont.config.svg2, ziamath.config.math.color)
    # Plain paths instead of <symbol>/<use>, so ids of separate formulas cannot clash.
    ziafont.config.svg2 = False
    ziamath.config.math.color = "currentColor"
    try:

        def replace(m: re.Match) -> str:
            try:
                svg = _render(ziamath, m.group(1), m.group(2))
            except Exception as e:  # noqa: BLE001 - any renderer error falls back to source
                tex = _tex_source(m.group(2))
                log(f"  Warning: could not render math {tex!r}: {e or type(e).__name__}")
                return _fallback(m.group(1), m.group(2))
            return f'<span class="math {_mode(m.group(1))}">{svg}</span>'

        return _MATH.sub(replace, html)
    finally:
        ziafont.config.svg2, ziamath.config.math.color = previous


def _mode(attrs: str) -> str:
    return "display" if 'display="block"' in attrs else "inline"


def _tex_source(inner: str) -> str:
    m = _ANNOTATION.search(inner)
    return html_lib.unescape(m.group(1)).strip() if m else ""


def _render(ziamath, attrs: str, inner: str) -> str:  # noqa: ANN001 - optional module
    body = _ANNOTATION.sub("", inner)
    body = re.sub(r"</?semantics\b[^>]*>", "", body)
    math = ziamath.Math(f"<math{attrs}>{body}</math>", size=_SIZE)
    missing = _missing_glyphs(math.font, body)
    if missing:
        # ziamath draws all text, \text{} included, in its math font.
        msg = f"the math font has no glyphs for {missing}"
        raise ValueError(msg)
    svg = math.svg()
    root = _SVG_ROOT.search(svg)
    if root is None:
        msg = "renderer returned no <svg>"
        raise ValueError(msg)
    tag = root.group(0)
    width = float(re.search(r'\bwidth="([\d.]+)"', tag).group(1))
    height = float(re.search(r'\bheight="([\d.]+)"', tag).group(1))
    view_box = re.search(r'\bviewBox="([^"]+)"', tag).group(1).split()
    # The baseline sits at y=0 of the viewBox; everything below it is descent.
    descent = height + float(view_box[1])
    style = (
        f"width:{width / _SIZE:.3f}em;height:{height / _SIZE:.3f}em;"
        f"vertical-align:{-descent / _SIZE:.3f}em"
    )
    new_tag = re.sub(r'\s(?:width|height)="[^"]*"', "", tag)
    new_tag = new_tag.replace("<svg", f'<svg class="math-svg" style="{style}"', 1)
    return svg.replace(tag, new_tag, 1)


def _missing_glyphs(font: object, body: str) -> str:
    """Return the characters of the MathML ``body`` that ``font`` cannot draw."""
    text = html_lib.unescape(re.sub(r"<[^>]*>", "", body))
    find = getattr(font, "glyphindex", None)
    if find is None:
        return ""
    chars = dict.fromkeys(c for c in text if not c.isspace() and not find(c))
    return "".join(chars)


def _fallback(attrs: str, inner: str) -> str:
    tex = html_lib.escape(_tex_source(inner), quote=False)
    return f'<span class="math {_mode(attrs)} math-source"><code>{tex}</code></span>'
