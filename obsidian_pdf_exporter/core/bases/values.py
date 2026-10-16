"""Value types of the Bases expression language: dates, durations, links and files."""

from __future__ import annotations

import datetime
import math
import re
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class Unsupported(Exception):  # noqa: N818 - reads as "the expression uses something unsupported"
    """The expression uses a function, field or syntax that is not supported."""


@dataclass
class FileRecord:
    """One file of the vault, as Bases sees it.

    Attributes:
        path: Absolute path.
        rel: Path relative to the vault root, with ``/``.
        frontmatter: Note properties (empty for other files).
        tags: Tags from the frontmatter and the text, without ``#``.
        links: Targets of the wiki and markdown links in the note.
        embeds: Targets of the embeds in the note.
    """

    path: Path
    rel: str
    frontmatter: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    embeds: list[str] = field(default_factory=list)
    size: int = 0
    ctime: float = 0.0
    mtime: float = 0.0

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def basename(self) -> str:
        name = self.name
        return name.rsplit(".", 1)[0] if "." in name else name

    @property
    def ext(self) -> str:
        name = self.name
        return name.rsplit(".", 1)[1] if "." in name else ""

    @property
    def folder(self) -> str:
        return self.rel.rsplit("/", 1)[0] if "/" in self.rel else "/"

    @property
    def link_target(self) -> str:
        """The wiki link target of this file: the path, without ``.md``."""
        return self.rel[:-3] if self.rel.lower().endswith(".md") else self.rel


@dataclass(frozen=True)
class Link:
    """A link to a file or URL, with optional display text."""

    target: str
    display: str = ""

    @property
    def name(self) -> str:
        """The file name the link points to, without folder, heading and ``.md``."""
        target = self.target.split("#", 1)[0].split("|", 1)[0].strip()
        name = target.rsplit("/", 1)[-1]
        return name[:-3] if name.lower().endswith(".md") else name


@dataclass(frozen=True)
class Regex:
    """A regular expression literal such as ``/abc/i``."""

    pattern: str
    flags: str = ""

    def compile(self) -> re.Pattern:
        flags = 0
        if "i" in self.flags:
            flags |= re.IGNORECASE
        if "m" in self.flags:
            flags |= re.MULTILINE
        if "s" in self.flags:
            flags |= re.DOTALL
        return re.compile(_js_regex(self.pattern), flags)


def _js_regex(pattern: str) -> str:
    # Named groups are written (?<name>...) in JavaScript.
    return re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", pattern)


@dataclass(frozen=True)
class Date:
    """A date, or a date with time."""

    value: datetime.datetime
    has_time: bool = True

    @classmethod
    def of(cls, value: datetime.date) -> Date:
        if isinstance(value, datetime.datetime):
            return cls(value.replace(tzinfo=None), has_time=True)
        return cls(datetime.datetime(value.year, value.month, value.day), has_time=False)

    @property
    def ms(self) -> float:
        return self.value.timestamp() * 1000

    def shift(self, duration: Duration, sign: int = 1) -> Date:
        value = _add_months(self.value, sign * duration.months)
        value += datetime.timedelta(milliseconds=sign * duration.ms)
        return Date(value, self.has_time or duration.ms % 86_400_000 != 0)


@dataclass(frozen=True)
class Duration:
    """A length of time: calendar months plus milliseconds."""

    months: int = 0
    ms: float = 0.0

    def scale(self, factor: float) -> Duration:
        return Duration(round(self.months * factor), self.ms * factor)


def _add_months(value: datetime.datetime, months: int) -> datetime.datetime:
    if not months:
        return value
    index = value.year * 12 + value.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    days = [31, 29 if _leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return value.replace(year=year, month=month, day=min(value.day, days[month - 1]))


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


_UNITS_MS = {
    "w": 7 * 86_400_000,
    "d": 86_400_000,
    "h": 3_600_000,
    "m": 60_000,
    "s": 1000,
    "ms": 1,
}
_UNIT_NAMES = {
    "y": "y",
    "year": "y",
    "years": "y",
    "M": "M",
    "month": "M",
    "months": "M",
    "w": "w",
    "week": "w",
    "weeks": "w",
    "d": "d",
    "day": "d",
    "days": "d",
    "h": "h",
    "hour": "h",
    "hours": "h",
    "m": "m",
    "minute": "m",
    "minutes": "m",
    "s": "s",
    "second": "s",
    "seconds": "s",
    "ms": "ms",
    "millisecond": "ms",
    "milliseconds": "ms",
}
_RE_DURATION_PART = re.compile(r"\s*([+-]?\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*,?")


def parse_duration(text: str) -> Duration | None:
    """Parse ``"1d"``, ``"2 weeks"`` or ``"1M 4h"``. Returns None for other text."""
    text = text.strip()
    if not text:
        return None
    months = 0
    ms = 0.0
    pos = 0
    while pos < len(text):
        m = _RE_DURATION_PART.match(text, pos)
        if m is None:
            return None
        amount = float(m.group(1))
        unit = _UNIT_NAMES.get(m.group(2)) or _UNIT_NAMES.get(m.group(2).lower())
        if unit is None or (m.group(2) == "M" and unit != "M"):
            return None
        if unit == "y":
            months += round(amount * 12)
        elif unit == "M":
            months += round(amount)
        else:
            ms += amount * _UNITS_MS[unit]
        pos = m.end()
    return Duration(months, ms)


_RE_ISO_DATE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?$"
)


def parse_date(text: str) -> Date | None:
    """Parse ``YYYY-MM-DD`` or ``YYYY-MM-DD HH:mm[:ss]``. Returns None for other text."""
    m = _RE_ISO_DATE.match(text.strip())
    if m is None:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        if m.group(4) is None:
            return Date(datetime.datetime(year, month, day), has_time=False)
        second = int(m.group(6) or 0)
        micro = int((m.group(7) or "0")[:6].ljust(6, "0"))
        value = datetime.datetime(year, month, day, int(m.group(4)), int(m.group(5)), second, micro)
    except ValueError:
        return None
    return Date(value, has_time=True)


# ---------------------------------------------------------------------------
# Moment.js formatting
# ---------------------------------------------------------------------------

_RE_MOMENT = re.compile(
    r"\[[^\]]*\]|YYYY|YY|MMMM|MMM|MM|M|Do|DD|D|dddd|ddd|dd|d|HH|H|hh|h|mm|m|ss|s|SSS|A|a|ZZ|Z|X|x"
)


def _hour12(v: datetime.datetime) -> int:
    return v.hour % 12 or 12


_MOMENT_TOKENS: dict[str, Callable[[datetime.datetime], str]] = {
    "YYYY": lambda v: f"{v.year:04d}",
    "YY": lambda v: f"{v.year % 100:02d}",
    "MMMM": lambda v: v.strftime("%B"),
    "MMM": lambda v: v.strftime("%b"),
    "MM": lambda v: f"{v.month:02d}",
    "M": lambda v: str(v.month),
    "Do": lambda v: f"{v.day}{_ordinal(v.day)}",
    "DD": lambda v: f"{v.day:02d}",
    "D": lambda v: str(v.day),
    "dddd": lambda v: v.strftime("%A"),
    "ddd": lambda v: v.strftime("%A")[:3],
    "dd": lambda v: v.strftime("%A")[:2],
    "d": lambda v: str((v.weekday() + 1) % 7),
    "HH": lambda v: f"{v.hour:02d}",
    "H": lambda v: str(v.hour),
    "hh": lambda v: f"{_hour12(v):02d}",
    "h": lambda v: str(_hour12(v)),
    "mm": lambda v: f"{v.minute:02d}",
    "m": lambda v: str(v.minute),
    "ss": lambda v: f"{v.second:02d}",
    "s": lambda v: str(v.second),
    "SSS": lambda v: f"{v.microsecond // 1000:03d}",
    "A": lambda v: "PM" if v.hour >= 12 else "AM",  # noqa: PLR2004
    "a": lambda v: "pm" if v.hour >= 12 else "am",  # noqa: PLR2004
    "X": lambda v: str(int(v.timestamp())),
    "x": lambda v: str(int(v.timestamp() * 1000)),
}


def format_date(date: Date, fmt: str) -> str:
    """Format ``date`` with a Moment.js format string such as ``YYYY-MM-DD``.

    Time zone tokens (``Z``, ``ZZ``) are left out: dates are in local time.
    """

    def token(m: re.Match) -> str:
        t = m.group(0)
        if t.startswith("["):
            return t[1:-1]
        fn = _MOMENT_TOKENS.get(t)
        return fn(date.value) if fn is not None else ""

    return _RE_MOMENT.sub(token, fmt)


def _ordinal(day: int) -> str:
    if 11 <= day % 100 <= 13:  # noqa: PLR2004
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def relative_date(date: Date, now: datetime.datetime) -> str:
    """Describe ``date`` relative to ``now`` like Moment.js ``fromNow``."""
    seconds = (now - date.value).total_seconds()
    future = seconds < 0
    seconds = abs(seconds)
    steps = [
        (45, "a few seconds", None),
        (90, "a minute", None),
        (45 * 60, None, ("minutes", 60)),
        (90 * 60, "an hour", None),
        (22 * 3600, None, ("hours", 3600)),
        (36 * 3600, "a day", None),
        (26 * 86400, None, ("days", 86400)),
        (45 * 86400, "a month", None),
        (320 * 86400, None, ("months", 30.4375 * 86400)),
        (548 * 86400, "a year", None),
    ]
    text = None
    for limit, fixed, unit in steps:
        if seconds < limit:
            text = fixed or f"{round(seconds / unit[1])} {unit[0]}"
            break
    if text is None:
        text = f"{round(seconds / (365.25 * 86400))} years"
    return f"in {text}" if future else f"{text} ago"


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def number_text(value: float) -> str:
    """Write a number the way JavaScript does."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == int(value) and abs(value) < 1e21:  # noqa: PLR2004
        return str(int(value))
    return repr(value)


def to_text(value: object) -> str:  # noqa: C901, PLR0911 - one branch per type
    """The ``toString()`` of a value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return number_text(value)
    if isinstance(value, str):
        return value
    if isinstance(value, Date):
        return format_date(value, "YYYY-MM-DD HH:mm:ss" if value.has_time else "YYYY-MM-DD")
    if isinstance(value, Link):
        return value.display or value.name
    if isinstance(value, FileRecord):
        return value.basename
    if isinstance(value, list):
        return ", ".join(to_text(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {to_text(v)}" for k, v in value.items())
    if isinstance(value, Duration):
        return number_text(value.ms + value.months * 30 * 86_400_000)
    if isinstance(value, Regex):
        return f"/{value.pattern}/{value.flags}"
    return str(value)
