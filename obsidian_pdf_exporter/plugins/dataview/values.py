"""The values of the Dataview query language: links, widgets, types, ordering and text.

Ports ``data-model/value.ts`` and parts of ``util/normalize.ts`` of Dataview.
Values are plain Python objects:

======== ==========================================================
Type     Python
======== ==========================================================
null     ``None``
boolean  ``bool``
number   ``int`` or ``float`` (printed like JavaScript numbers)
string   ``str``
date     :class:`~obsidian_pdf_exporter.plugins.dataview.luxon.DateTime`
duration :class:`~obsidian_pdf_exporter.plugins.dataview.luxon.Duration`
link     :class:`Link`
array    ``list``
object   ``dict``
function a callable ``(context, *args)``
widget   :class:`ListPair` or :class:`ExternalLink`
======== ==========================================================
"""

from __future__ import annotations

import functools
import math
import re
import unicodedata
from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields
from dataclasses import replace
from typing import Any

from obsidian_pdf_exporter.plugins.dataview.luxon import DateTime
from obsidian_pdf_exporter.plugins.dataview.luxon import Duration

Literal = Any

##############
# Settings   #
##############


@dataclass
class Settings:
    """Dataview settings, as stored in ``.obsidian/plugins/dataview/data.json``."""

    renderNullAs: str = "\\-"
    warnOnEmptyResult: bool = True
    defaultDateFormat: str = "MMMM dd, yyyy"
    defaultDateTimeFormat: str = "h:mm a - MMMM dd, yyyy"
    maxRecursiveRenderDepth: int = 4
    tableIdColumnName: str = "File"
    tableGroupColumnName: str = "Group"
    showResultCount: bool = True
    allowHtml: bool = True
    inlineQueryPrefix: str = "="
    inlineJsQueryPrefix: str = "$="
    inlineQueriesInCodeblocks: bool = True
    enableInlineDataview: bool = True
    enableDataviewJs: bool = True
    enableInlineDataviewJs: bool = True
    prettyRenderInlineFields: bool = True
    dataviewJsKeyword: str = "dataviewjs"
    recursiveSubTaskCompletion: bool = False
    taskCompletionTracking: bool = False
    taskCompletionUseEmojiShorthand: bool = False
    taskCompletionText: str = "completion"
    taskCompletionDateFormat: str = "yyyy-MM-dd"
    refreshEnabled: bool = True
    refreshInterval: int = 2500
    prettyRenderInlineFieldsInLivePreview: bool = True
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        """Settings from the data.json content; unknown keys are kept in ``extra``."""
        known = {f.name: f for f in fields(cls) if f.name != "extra"}
        values: dict[str, Any] = {}
        extra = {}
        for key, value in data.items():
            if key in known and isinstance(value, type(getattr(cls(), key))):
                values[key] = value
            else:
                extra[key] = value
        return replace(cls(), **values, extra=extra)

    def to_dict(self) -> dict:
        out = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "extra"}
        out.update(self.extra)
        return out


DEFAULT_SETTINGS = Settings()


##############
# Links      #
##############


def get_file_title(path: str) -> str:
    """The file name without folders and without ``.md``."""
    if "/" in path:
        path = path[path.rfind("/") + 1 :]
    return path.removesuffix(".md")


def get_parent_folder(path: str) -> str:
    return "/".join(path.split("/")[:-1])


def get_extension(path: str) -> str:
    if "." not in path:
        return ""
    return path[path.rfind(".") + 1 :]


def _is_emoji(ch: str) -> bool:
    o = ord(ch)
    return (
        0x1F000 <= o <= 0x1FAFF
        or 0x2600 <= o <= 0x27BF
        or 0x2300 <= o <= 0x23FF
        or 0x2B00 <= o <= 0x2BFF
        or 0x1F900 <= o <= 0x1F9FF
        or o in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299)
        or 0x2194 <= o <= 0x21AA
        or 0x25AA <= o <= 0x25FE
        or 0x2934 <= o <= 0x2935
    )


#: One emoji with its modifiers: variation selector, skin tone, keycap or a ZWJ sequence.
EMOJI_TAIL = "️⃣‍"


def match_emoji(text: str, pos: int) -> int:
    """The end of the emoji that starts at ``pos``, or -1 when there is none."""
    if pos >= len(text) or not _is_emoji(text[pos]):
        return -1
    end = pos + 1
    while end < len(text):
        ch = text[end]
        if ch in "️⃣" or 0x1F3FB <= ord(ch) <= 0x1F3FF:
            end += 1
        elif ch == "‍" and end + 1 < len(text) and _is_emoji(text[end + 1]):
            end += 2
        else:
            break
    return end


def is_letter(ch: str) -> bool:
    r"""``\p{Letter}``."""
    return unicodedata.category(ch).startswith("L")


def _word_char(ch: str) -> bool:
    return (ch.isdigit() and ch.isascii()) or is_letter(ch) or ch in "_-"


@functools.lru_cache(maxsize=65536)
def canonicalize_var_name(name: str) -> str:
    """Dataview's key normalisation: ``Due Date`` becomes ``due-date``."""
    out = []
    i = 0
    n = len(name)
    while i < n:
        end = match_emoji(name, i)
        if end > 0:
            out.append(name[i:end])
            i = end
            continue
        ch = name[i]
        if _word_char(ch):
            j = i
            while j < n and _word_char(name[j]) and match_emoji(name, j) < 0:
                j += 1
            out.append(name[i:j].lower())
            i = j
        elif ch.isspace():
            j = i
            while j < n and name[j].isspace():
                j += 1
            out.append("-")
            i = j
        else:
            i += 1
    return "".join(out)


@functools.lru_cache(maxsize=65536)
def normalize_header_for_link(header: str) -> str:
    """Collapse a heading into the form Obsidian links to (punctuation becomes spaces)."""
    out = []
    i = 0
    n = len(header)
    while i < n:
        end = match_emoji(header, i)
        if end > 0:
            out.append(header[i:end])
            i = end
            continue
        ch = header[i]
        if _word_char(ch):
            out.append(ch)
        else:
            out.append(" ")
        i += 1
    return " ".join("".join(out).split())


class Link:
    """A link to a file, a heading or a block, like Dataview's ``Link``."""

    __slots__ = ("display", "embed", "path", "subpath", "type")

    def __init__(
        self,
        path: str,
        *,
        display: str | None = None,
        subpath: str | None = None,
        embed: bool = False,
        link_type: str = "file",
    ) -> None:
        self.path = path
        self.display = display
        self.subpath = subpath
        self.embed = embed
        self.type = link_type

    @staticmethod
    def file(path: str, embed: bool = False, display: str | None = None) -> Link:
        return Link(path, display=display, embed=embed)

    @staticmethod
    def header(
        path: str,
        header: str,
        embed: bool = False,
        display: str | None = None,
    ) -> Link:
        return Link(
            path,
            display=display,
            subpath=normalize_header_for_link(header),
            embed=embed,
            link_type="header",
        )

    @staticmethod
    def block(
        path: str,
        block_id: str,
        embed: bool = False,
        display: str | None = None,
    ) -> Link:
        return Link(path, display=display, subpath=block_id, embed=embed, link_type="block")

    @staticmethod
    def infer(linkpath: str, embed: bool = False, display: str | None = None) -> Link:
        if "#^" in linkpath:
            parts = linkpath.split("#^")
            return Link.block(parts[0], parts[1], embed, display)
        if "#" in linkpath:
            parts = linkpath.split("#")
            return Link.header(parts[0], parts[1], embed, display)
        return Link.file(linkpath, embed, display)

    def _copy(self, **changes: Any) -> Link:
        data = {
            "display": self.display,
            "subpath": self.subpath,
            "embed": self.embed,
            "link_type": self.type,
        }
        data.update(changes)
        path = data.pop("path", self.path)
        return Link(path, **data)

    def equals(self, other: object) -> bool:
        return (
            isinstance(other, Link)
            and self.path == other.path
            and self.type == other.type
            and self.subpath == other.subpath
        )

    def with_path(self, path: str) -> Link:
        return self._copy(path=path)

    def with_display(self, display: str | None) -> Link:
        return self._copy(display=display)

    def with_header(self, header: str) -> Link:
        return Link.header(self.path, header, self.embed, self.display)

    def to_file(self) -> Link:
        return Link.file(self.path, self.embed, self.display)

    def to_embed(self) -> Link:
        return self if self.embed else self._copy(embed=True)

    def from_embed(self) -> Link:
        return self._copy(embed=False) if self.embed else self

    def obsidian_link(self) -> str:
        escaped = self.path.replace("|", "\\|")
        subpath = (self.subpath or "").replace("|", "\\|")
        if self.type == "header":
            return f"{escaped}#{subpath}"
        if self.type == "block":
            return f"{escaped}#^{subpath}"
        return escaped

    def display_text(self) -> str:
        """The text Obsidian shows for the link."""
        if self.display:
            return self.display
        text = get_file_title(self.path)
        if self.type in ("header", "block"):
            text += " > " + (self.subpath or "")
        return text

    def markdown(self) -> str:
        return (
            ("!" if self.embed else "")
            + "[["
            + self.obsidian_link()
            + "|"
            + self.display_text()
            + "]]"
        )

    def file_name(self) -> str:
        return get_file_title(self.path).replace(".md", "", 1)

    def to_object(self) -> dict:
        return {
            "path": self.path,
            "type": self.type,
            "subpath": self.subpath,
            "display": self.display,
            "embed": self.embed,
        }

    def __repr__(self) -> str:
        return f"Link({self.markdown()})"

    def __str__(self) -> str:
        return self.markdown()


##############
# Widgets    #
##############


class Widget:
    """A value with its own rendering."""

    widget: str = ""

    def markdown(self) -> str:
        raise NotImplementedError


class ListPair(Widget):
    """``key: value``, the items of ``LIST expr`` queries."""

    widget = "dataview:list-pair"

    def __init__(self, key: Literal, value: Literal) -> None:
        self.key = key
        self.value = value

    def markdown(self) -> str:
        return f"{to_string(self.key)}: {to_string(self.value)}"


class ExternalLink(Widget):
    """A link to a URL, made by ``elink``."""

    widget = "dataview:external-link"

    def __init__(self, url: str, display: str | None = None) -> None:
        self.url = url
        self.display = display

    def markdown(self) -> str:
        return f"[{self.display if self.display is not None else self.url}]({self.url})"


class HtmlValue:
    """Raw HTML produced by DataviewJS (``dv.el`` elements)."""

    def __init__(self, html: str, name: str = "HTMLElement") -> None:
        self.html = html
        self.name = name


class ClassInstance:
    """A JavaScript object that is not a plain object, shown as ``<Name>``."""

    def __init__(self, name: str) -> None:
        self.name = name


##############
# Types      #
##############


def type_of(value: Literal) -> str | None:
    """The Dataview type name of ``value`` (``Values.typeOf``)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Duration):
        return "duration"
    if isinstance(value, DateTime):
        return "date"
    if isinstance(value, Widget):
        return "widget"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Link):
        return "link"
    if callable(value):
        return "function"
    if isinstance(value, HtmlValue):
        return "html"
    if isinstance(value, (dict, ClassInstance)):
        return "object"
    return None


def is_truthy(value: Literal) -> bool:
    """``Values.isTruthy``: non-null and with data in it."""
    t = type_of(value)
    if t == "number":
        return value != 0 and not (isinstance(value, float) and math.isnan(value))
    if t in ("string", "array"):
        return len(value) > 0
    if t == "boolean":
        return value
    if t == "link":
        return bool(value.path)
    if t == "date":
        return value.ts != 0
    if t == "duration":
        return value.to_millis() != 0
    if t == "object":
        return isinstance(value, ClassInstance) or len(value) > 0
    return t in ("html", "widget", "function")


def deep_copy(value: Literal) -> Literal:
    if isinstance(value, list):
        return [deep_copy(v) for v in value]
    if isinstance(value, dict):
        return {k: deep_copy(v) for k, v in value.items()}
    return value


def map_leaves(value: Literal, fn: Any) -> Literal:
    if isinstance(value, dict):
        return {k: map_leaves(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [map_leaves(v, fn) for v in value]
    return fn(value)


##############
# Numbers    #
##############


def js_number(value: float) -> str:
    """``String(value)`` for a JavaScript number."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if abs(value) < 10**21:
            return str(value)
        value = float(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    digits, exponent = _shortest_digits(abs(value))
    k = len(digits)
    n = exponent + k  # position of the decimal point
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    exp = f"e{'+' if e >= 0 else '-'}{abs(e)}"
    if k == 1:
        return sign + digits + exp
    return sign + digits[0] + "." + digits[1:] + exp


def _shortest_digits(value: float) -> tuple[str, int]:
    """Shortest round-trip digits and exponent: ``value == int(digits) * 10**exponent``."""
    text = repr(value)
    if "e" in text:
        mantissa, exp_text = text.split("e")
        exp = int(exp_text)
    else:
        mantissa, exp = text, 0
    if "." in mantissa:
        whole, frac = mantissa.split(".")
    else:
        whole, frac = mantissa, ""
    if frac == "0":
        frac = ""
    digits = (whole + frac).lstrip("0") or "0"
    exp -= len(frac)
    stripped = digits.rstrip("0")
    exp += len(digits) - len(stripped)
    return stripped or "0", exp


def js_div(a: float, b: float) -> float:
    if b == 0:
        if a == 0 or (isinstance(a, float) and math.isnan(a)):
            return math.nan
        return math.inf if (a > 0) == (math.copysign(1, b) > 0) else -math.inf
    result = a / b
    return (
        int(result)
        if isinstance(result, float) and result.is_integer() and abs(result) < 2**53
        else result
    )


def js_mod(a: float, b: float) -> float:
    if b == 0:
        return math.nan
    result = math.fmod(a, b)
    if isinstance(a, int) and isinstance(b, int):
        return int(result)
    return result


def num(value: float) -> float:
    """Keep integral floats as ints, so they print like JavaScript numbers."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return int(value)
    return value


##############
# Collation  #
##############

# The order of ASCII punctuation and symbols in the CLDR root collation,
# which ``String.prototype.localeCompare`` uses.
_PUNCT_ORDER = "_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"
_PUNCT_RANK = {ch: i for i, ch in enumerate(_PUNCT_ORDER)}
_EXPANSIONS = {"ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ø": "o", "Ø": "O"}


def _char_weights(ch: str) -> tuple[tuple[int, int], int, int]:
    """Primary (class, weight), secondary and tertiary weight of one character."""
    if ch.isspace():
        return (0, ord(ch)), 0, 0
    if ch in _PUNCT_RANK:
        rank = _PUNCT_RANK[ch]
        return ((3, rank) if ch == "$" else (1, rank)), 0, 0
    cat = unicodedata.category(ch)
    if ch.isdigit():
        try:
            return (4, unicodedata.digit(ch)), 0, 0
        except (TypeError, ValueError):
            return (4, ord(ch)), 0, 0
    if cat.startswith("L"):
        decomposed = unicodedata.normalize("NFD", ch)
        base = decomposed[0]
        accents = sum(ord(c) for c in decomposed[1:])
        lower = base.lower()
        tertiary = 0 if base == lower else 1
        return (5, ord(lower[0])), accents, tertiary
    if cat.startswith("M"):
        return (-1, 0), ord(ch), 0
    if cat == "Sc":
        return (3, 100 + ord(ch)), 0, 0
    if cat.startswith("P"):
        return (1, 100 + ord(ch)), 0, 0
    if cat.startswith("S"):
        return (2, ord(ch)), 0, 0
    if cat.startswith("C"):
        return (-1, 0), 0, 0
    return (6, ord(ch)), 0, 0


def collation_key(text: str) -> tuple:
    """A sort key that orders strings like ``localeCompare`` in the root locale."""
    primary = []
    secondary = []
    tertiary = []
    for raw in text:
        for ch in _EXPANSIONS.get(raw, raw):
            p, s, t = _char_weights(ch)
            if p[0] == -1:
                if s and secondary:
                    secondary[-1] += s
                continue
            primary.append(p)
            secondary.append(s)
            tertiary.append(t)
    return (tuple(primary), tuple(secondary), tuple(tertiary))


def locale_compare(a: str, b: str) -> int:
    if a == b:
        return 0
    ka, kb = collation_key(a), collation_key(b)
    if ka == kb:
        return (a > b) - (a < b)
    return -1 if ka < kb else 1


##############
# Ordering   #
##############


def compare_value(a: Literal, b: Literal, normalize: Any = None) -> int:
    """``Values.compareValue``: a total order over every Dataview value."""
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    ta, tb = type_of(a), type_of(b)
    if ta is None and tb is None:
        return 0
    if ta is None:
        return -1
    if tb is None:
        return 1
    if ta != tb:
        return locale_compare(ta, tb)
    if a is b:
        return 0
    if ta == "string":
        return locale_compare(a, b)
    if ta == "number":
        if a < b:
            return -1
        return 0 if a == b else 1
    if ta == "boolean":
        if a == b:
            return 0
        return 1 if a else -1
    if ta == "link":
        norm = normalize or (lambda x: x)
        path_cmp = locale_compare(norm(a.path), norm(b.path))
        if path_cmp != 0:
            return path_cmp
        type_cmp = locale_compare(a.type, b.type)
        if type_cmp != 0:
            return type_cmp
        if a.subpath and not b.subpath:
            return 1
        if not a.subpath and b.subpath:
            return -1
        if not a.subpath and not b.subpath:
            return 0
        return locale_compare(a.subpath or "", b.subpath or "")
    if ta == "date":
        if a.ts < b.ts:
            return -1
        return 0 if a.equals(b) else 1
    if ta == "duration":
        if a.to_millis() < b.to_millis():
            return -1
        return 0 if a.equals(b) else 1
    if ta == "array":
        for x, y in zip(a, b, strict=False):
            c = compare_value(x, y)
            if c != 0:
                return c
        return len(a) - len(b)
    if ta == "object":
        if not isinstance(a, dict) or not isinstance(b, dict):
            return 0
        k1 = sorted(a.keys())
        k2 = sorted(b.keys())
        c = compare_value(k1, k2)
        if c != 0:
            return c
        for key in k1:
            c = compare_value(a[key], b[key])
            if c != 0:
                return c
        return 0
    return 0


##############
# Text       #
##############


def render_minimal_duration(dur: Duration) -> str:
    """Dataview's duration text: normalized, zero units dropped, ``toHuman``."""
    dur = dur.shift_to_all().normalize()
    return Duration({u: v for u, v in dur.values.items() if v != 0}).to_human()


def to_string(
    value: Literal,
    settings: Settings = DEFAULT_SETTINGS,
    recursive: bool = False,
) -> str:
    """``Values.toString``: a Markdown-friendly text of any value."""
    t = type_of(value)
    if t is None or t == "null":
        return settings.renderNullAs
    if t == "string":
        return value
    if t in ("number", "boolean"):
        return js_number(value)
    if t == "html":
        return value.html
    if t in ("widget", "link"):
        return value.markdown()
    if t == "function":
        return "<function>"
    if t == "array":
        inner = ", ".join(to_string(v, settings, True) for v in value)
        return f"[{inner}]" if recursive else inner
    if t == "object":
        if isinstance(value, ClassInstance):
            return "{  }"
        inner = ", ".join(f"{k}: {to_string(v, settings, True)}" for k, v in value.items())
        return "{ " + inner + " }"
    if t == "date":
        if value.second == 0 and value.hour == 0 and value.minute == 0:
            return value.to_format(settings.defaultDateFormat)
        return value.to_format(settings.defaultDateTimeFormat)
    if t == "duration":
        return render_minimal_duration(value)
    return ""


def render_minimal_date(value: DateTime, settings: Settings) -> str:
    """How a date shows in a view: in the local zone, with the default formats."""
    if value.second == 0 and value.minute == 0 and value.hour == 0:
        return value.to_local().to_format(settings.defaultDateFormat)
    return value.to_local().to_format(settings.defaultDateTimeFormat)


def extract_date(text: str) -> DateTime | None:
    """A ``YYYY-MM-DD`` or ``YYYYMMDD`` date anywhere in ``text``."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text) or re.search(r"(\d{4})(\d{2})(\d{2})", text)
    if not m:
        return None
    try:
        return DateTime.from_object(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def strip_time(dt: DateTime) -> DateTime:
    return DateTime.from_object(dt.year, dt.month, dt.day)
