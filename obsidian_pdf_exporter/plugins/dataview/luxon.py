"""Dates and durations with the semantics of Luxon 3.4, the date library of Dataview.

Dataview keeps every date as a Luxon ``DateTime`` and every duration as a
Luxon ``Duration``. This module mirrors the parts of both that Dataview uses:
time zones (the local zone, fixed offsets and IANA zones), calendar
arithmetic, ``diff``, ``startOf`` and ``endOf``, the ``toFormat`` tokens
(English names), ``fromFormat``, the casual conversion matrix of durations
(a month is 30 days, a year 365 days), ``shiftTo``, ``normalize`` and
``toHuman``.
"""

from __future__ import annotations

import calendar
import datetime
import math
import re
from dataclasses import dataclass
from typing import ClassVar

try:  # pragma: no cover - zoneinfo is part of Python 3.9+, tzdata may be missing on Windows
    import zoneinfo
except ImportError:  # pragma: no cover
    zoneinfo = None  # type: ignore[assignment]

_EPOCH = datetime.datetime(1970, 1, 1)
_UTC = datetime.timezone.utc

MONTHS_LONG = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
MONTHS_SHORT = tuple(m[:3] for m in MONTHS_LONG)
WEEKDAYS_LONG = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
WEEKDAYS_SHORT = tuple(d[:3] for d in WEEKDAYS_LONG)


class InvalidDateError(ValueError):
    """A date or time that does not exist, like February 30."""


###########
# Zones   #
###########


class Zone:
    """A time zone: maps an instant (epoch milliseconds) to an offset in minutes."""

    name: str = ""
    fixed: bool = False

    def offset(self, ts: int) -> int:
        """Offset from UTC in minutes at the instant ``ts``."""
        raise NotImplementedError

    def ts_of(self, wall: datetime.datetime) -> int:
        """The instant at which the clock in this zone shows ``wall``."""
        guess = _wall_ms(wall) - self.offset(_wall_ms(wall)) * 60_000
        # Second pass, as in Luxon's fixOffset, for wall times near a change.
        o2 = self.offset(guess)
        return _wall_ms(wall) - o2 * 60_000

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Zone) and other.name == self.name

    def __hash__(self) -> int:
        return hash(self.name)


class LocalZone(Zone):
    """The zone of the machine that runs the export."""

    name = "local"

    def offset(self, ts: int) -> int:
        utc = datetime.datetime.fromtimestamp(0, _UTC) + datetime.timedelta(milliseconds=ts)
        try:
            local = utc.astimezone()
        except (OverflowError, OSError, ValueError):
            local = datetime.datetime.now().astimezone()
        delta = local.utcoffset() or datetime.timedelta(0)
        return round(delta.total_seconds() / 60)

    def ts_of(self, wall: datetime.datetime) -> int:
        try:
            return round(wall.timestamp() * 1000)
        except (OverflowError, OSError, ValueError):
            return super().ts_of(wall)


class FixedZone(Zone):
    """A fixed offset from UTC, like ``UTC+2``."""

    fixed = True

    def __init__(self, minutes: int) -> None:
        self.minutes = minutes
        if minutes == 0:
            self.name = "UTC"
        else:
            sign = "+" if minutes > 0 else "-"
            hours, mins = divmod(abs(minutes), 60)
            self.name = f"UTC{sign}{hours}" + (f":{mins:02d}" if mins else "")

    def offset(self, ts: int) -> int:
        return self.minutes


class IANAZone(Zone):
    """A named zone of the IANA database, like ``Europe/Berlin``."""

    def __init__(self, name: str) -> None:
        if zoneinfo is None:
            msg = f"unknown time zone {name}"
            raise InvalidDateError(msg)
        try:
            self.info = zoneinfo.ZoneInfo(name)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
            msg = f"unknown time zone {name}"
            raise InvalidDateError(msg) from e
        self.name = name

    def offset(self, ts: int) -> int:
        utc = datetime.datetime.fromtimestamp(0, _UTC) + datetime.timedelta(milliseconds=ts)
        delta = utc.astimezone(self.info).utcoffset() or datetime.timedelta(0)
        return round(delta.total_seconds() / 60)


LOCAL = LocalZone()
UTC = FixedZone(0)

_RE_FIXED = re.compile(r"^utc(?:([+-]\d{1,2})(?::(\d{2}))?)?$", re.IGNORECASE)


def parse_zone(spec: str | Zone) -> Zone:
    """Turn a zone name (``local``, ``utc``, ``UTC+5:30``, ``Europe/Berlin``) into a zone."""
    if isinstance(spec, Zone):
        return spec
    lowered = spec.strip().lower()
    if lowered in ("local", "system", "default"):
        return LOCAL
    if lowered in ("utc", "gmt", "z"):
        return UTC
    m = _RE_FIXED.match(lowered)
    if m:
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        return FixedZone(hours * 60 + (minutes if hours >= 0 else -minutes))
    return IANAZone(spec.strip())


def _wall_ms(wall: datetime.datetime) -> int:
    delta = wall - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _wall_of(ms: int) -> datetime.datetime:
    return _EPOCH + datetime.timedelta(milliseconds=ms)


##############
# DateTime   #
##############

_FROZEN_NOW: list[int] = []


def set_now(ts: int | None) -> None:
    """Freeze ``now`` (and ``today``) at the epoch milliseconds ``ts``, or unfreeze with None."""
    _FROZEN_NOW.clear()
    if ts is not None:
        _FROZEN_NOW.append(int(ts))


_UNIT_ALIASES = {
    "year": "years",
    "years": "years",
    "quarter": "quarters",
    "quarters": "quarters",
    "month": "months",
    "months": "months",
    "week": "weeks",
    "weeks": "weeks",
    "day": "days",
    "days": "days",
    "hour": "hours",
    "hours": "hours",
    "minute": "minutes",
    "minutes": "minutes",
    "second": "seconds",
    "seconds": "seconds",
    "millisecond": "milliseconds",
    "milliseconds": "milliseconds",
}


def normalize_unit(unit: str) -> str:
    """The plural Luxon unit name for ``unit`` (``day`` and ``days`` give ``days``)."""
    try:
        return _UNIT_ALIASES[unit.lower()]
    except KeyError:
        msg = f"Invalid unit {unit}"
        raise ValueError(msg) from None


class DateTime:
    """An instant with a zone, like Luxon's ``DateTime``. Immutable."""

    __slots__ = ("_c", "o", "ts", "zone")

    def __init__(self, ts: int, zone: Zone = LOCAL) -> None:
        self.ts = int(ts)
        self.zone = zone
        self.o = zone.offset(self.ts)
        self._c = _wall_of(self.ts + self.o * 60_000)

    # -- construction --------------------------------------------------------

    @classmethod
    def from_wall(cls, wall: datetime.datetime, zone: Zone = LOCAL) -> DateTime:
        """The instant at which the clock in ``zone`` shows ``wall``."""
        return cls(zone.ts_of(wall), zone)

    @classmethod
    def from_object(
        cls,
        year: int,
        month: int = 1,
        day: int = 1,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        millisecond: int = 0,
        zone: Zone = LOCAL,
    ) -> DateTime:
        """Build a date from its parts. Raises :class:`InvalidDateError` for impossible dates."""
        try:
            wall = datetime.datetime(year, month, day, hour, minute, second, millisecond * 1000)
        except (ValueError, OverflowError) as e:
            raise InvalidDateError(str(e)) from e
        return cls.from_wall(wall, zone)

    @classmethod
    def from_millis(cls, ms: float, zone: Zone = LOCAL) -> DateTime:
        """The instant ``ms`` milliseconds after the epoch."""
        return cls(round(ms), zone)

    @classmethod
    def now(cls) -> DateTime:
        """The current instant in the local zone (or the instant set with :func:`set_now`)."""
        if _FROZEN_NOW:
            return cls(_FROZEN_NOW[0], LOCAL)
        return cls(round(datetime.datetime.now(_UTC).timestamp() * 1000), LOCAL)

    # -- parts ---------------------------------------------------------------

    @property
    def wall(self) -> datetime.datetime:
        """The wall clock time in the zone, as a naive :class:`datetime.datetime`."""
        return self._c

    year = property(lambda self: self._c.year)
    month = property(lambda self: self._c.month)
    day = property(lambda self: self._c.day)
    hour = property(lambda self: self._c.hour)
    minute = property(lambda self: self._c.minute)
    second = property(lambda self: self._c.second)
    millisecond = property(lambda self: self._c.microsecond // 1000)
    weekday = property(lambda self: self._c.isoweekday())
    week_number = property(lambda self: self._c.isocalendar()[1])
    week_year = property(lambda self: self._c.isocalendar()[0])
    ordinal = property(lambda self: self._c.timetuple().tm_yday)
    quarter = property(lambda self: (self._c.month - 1) // 3 + 1)

    @property
    def days_in_month(self) -> int:
        return calendar.monthrange(self.year, self.month)[1]

    @property
    def is_offset_fixed(self) -> bool:
        return self.zone.fixed

    def to_millis(self) -> int:
        return self.ts

    # -- zones ---------------------------------------------------------------

    def set_zone(self, zone: Zone | str, *, keep_local_time: bool = False) -> DateTime:
        """The same instant in another zone, or the same wall time with ``keep_local_time``."""
        zone = parse_zone(zone)
        if keep_local_time:
            return DateTime.from_wall(self._c, zone)
        return DateTime(self.ts, zone)

    def to_local(self) -> DateTime:
        return self.set_zone(LOCAL)

    def to_utc(self) -> DateTime:
        return self.set_zone(UTC)

    # -- arithmetic ----------------------------------------------------------

    def set(self, **parts: int) -> DateTime:
        """A copy with some wall clock parts replaced (``year=``, ``day=``, ...)."""
        values = {
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "hour": self.hour,
            "minute": self.minute,
            "second": self.second,
            "millisecond": self.millisecond,
        }
        values.update(parts)
        return DateTime.from_object(**values, zone=self.zone)

    def plus(self, dur: Duration | dict) -> DateTime:
        """Add a duration: calendar units on the wall clock, time units as milliseconds."""
        if isinstance(dur, dict):
            dur = Duration(dur)
        v = dur.values
        years = v.get("years", 0)
        months = v.get("months", 0)
        quarters = v.get("quarters", 0)
        weeks = v.get("weeks", 0)
        days = v.get("days", 0)
        year = self.year + math.trunc(years)
        month = self.month + math.trunc(months) + math.trunc(quarters) * 3
        year += (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(self.day, calendar.monthrange(year, month)[1])
        try:
            wall = datetime.datetime(year, month, day) + datetime.timedelta(
                days=math.trunc(days) + math.trunc(weeks) * 7,
                hours=self.hour,
                minutes=self.minute,
                seconds=self.second,
                milliseconds=self.millisecond,
            )
        except (ValueError, OverflowError) as e:
            raise InvalidDateError(str(e)) from e
        rest = Duration(
            {
                "years": years - math.trunc(years),
                "quarters": quarters - math.trunc(quarters),
                "months": months - math.trunc(months),
                "weeks": weeks - math.trunc(weeks),
                "days": days - math.trunc(days),
                "hours": v.get("hours", 0),
                "minutes": v.get("minutes", 0),
                "seconds": v.get("seconds", 0),
                "milliseconds": v.get("milliseconds", 0),
            }
        ).as_unit("milliseconds")
        ts = self.zone.ts_of(wall)
        if rest:
            ts += round(rest)
        return DateTime(ts, self.zone)

    def minus(self, dur: Duration | dict) -> DateTime:
        if isinstance(dur, dict):
            dur = Duration(dur)
        return self.plus(dur.negate())

    def start_of(self, unit: str) -> DateTime:
        """The first instant of the year, quarter, month, week (Monday), day, hour, ... ."""
        unit = normalize_unit(unit)
        c = self._c
        if unit == "years":
            wall = datetime.datetime(c.year, 1, 1)
        elif unit == "quarters":
            wall = datetime.datetime(c.year, (c.month - 1) // 3 * 3 + 1, 1)
        elif unit == "months":
            wall = datetime.datetime(c.year, c.month, 1)
        elif unit == "weeks":
            wall = datetime.datetime(c.year, c.month, c.day) - datetime.timedelta(
                days=c.isoweekday() - 1
            )
        elif unit == "days":
            wall = datetime.datetime(c.year, c.month, c.day)
        elif unit == "hours":
            wall = c.replace(minute=0, second=0, microsecond=0)
        elif unit == "minutes":
            wall = c.replace(second=0, microsecond=0)
        elif unit == "seconds":
            wall = c.replace(microsecond=0)
        else:
            return self
        return DateTime.from_wall(wall, self.zone)

    def end_of(self, unit: str) -> DateTime:
        unit = normalize_unit(unit)
        return self.start_of(unit).plus({unit: 1}).minus({"milliseconds": 1})

    def diff(self, other: DateTime, units: list[str]) -> Duration:
        """``self - other`` in the given units, like Luxon's ``DateTime.diff``."""
        units = [normalize_unit(u) for u in units]
        other_is_later = other.ts > self.ts
        earlier, later = (self, other) if other_is_later else (other, self)
        diffed = _diff(earlier, later, units)
        return diffed.negate() if other_is_later else diffed

    # -- comparison ----------------------------------------------------------

    def equals(self, other: object) -> bool:
        """Same instant and same zone, as Luxon's ``equals``."""
        return isinstance(other, DateTime) and self.ts == other.ts and self.zone == other.zone

    def __eq__(self, other: object) -> bool:
        return isinstance(other, DateTime) and self.ts == other.ts and self.zone == other.zone

    def __hash__(self) -> int:
        return hash(self.ts)

    def __lt__(self, other: DateTime) -> bool:
        return self.ts < other.ts

    def __repr__(self) -> str:
        return f"DateTime({self.to_iso()})"

    # -- output --------------------------------------------------------------

    def to_iso(self) -> str:
        """ISO 8601 with milliseconds and offset, like ``2024-05-01T10:00:00.000+02:00``."""
        c = self._c
        return (
            f"{c.year:04d}-{c.month:02d}-{c.day:02d}T{c.hour:02d}:{c.minute:02d}:"
            f"{c.second:02d}.{c.microsecond // 1000:03d}{format_offset(self.o, 'short')}"
        )

    def to_format(self, fmt: str) -> str:
        """Format with Luxon tokens (``yyyy-MM-dd``, ``MMMM dd, yyyy``, ``h:mm a``)."""
        return "".join(val if literal else self._token(val) for literal, val in parse_format(fmt))

    def _token(self, part: str) -> str:
        simple = _DT_TOKENS.get(part)
        if simple is not None:
            value, pad = simple(self)
            return _num(value, pad)
        if part == "a":
            return "AM" if self.hour < 12 else "PM"
        if part in ("ccc", "EEE"):
            return WEEKDAYS_SHORT[self.weekday - 1]
        if part in ("cccc", "EEEE"):
            return WEEKDAYS_LONG[self.weekday - 1]
        if part in ("ccccc", "EEEEE"):
            return WEEKDAYS_LONG[self.weekday - 1][0]
        if part in ("LLL", "MMM"):
            return MONTHS_SHORT[self.month - 1]
        if part in ("LLLL", "MMMM"):
            return MONTHS_LONG[self.month - 1]
        if part in ("LLLLL", "MMMMM"):
            return MONTHS_LONG[self.month - 1][0]
        if part == "Z":
            return format_offset(self.o, "narrow")
        if part == "ZZ":
            return format_offset(self.o, "short")
        if part == "ZZZ":
            return format_offset(self.o, "techie")
        if part in ("ZZZZ", "ZZZZZ"):
            return _offset_name(self, long=part == "ZZZZZ")
        if part == "z":
            return self.zone.name if not isinstance(self.zone, LocalZone) else _local_zone_name()
        if part in ("G", "GG", "GGGGG"):
            ad = self.year > 0
            return {"G": ("AD", "BC"), "GG": ("Anno Domini", "Before Christ")}.get(
                part, ("A", "B")
            )[0 if ad else 1]
        macro = _MACROS.get(part)
        if macro is not None:
            return self.to_format(macro)
        return part


def _num(value: int, pad: int) -> str:
    text = str(abs(value))
    text = text.rjust(pad, "0")
    return ("-" if value < 0 else "") + text


_DT_TOKENS = {
    "S": lambda d: (d.millisecond, 0),
    "u": lambda d: (d.millisecond, 3),
    "SSS": lambda d: (d.millisecond, 3),
    "s": lambda d: (d.second, 0),
    "ss": lambda d: (d.second, 2),
    "uu": lambda d: (d.millisecond // 10, 2),
    "uuu": lambda d: (d.millisecond // 100, 0),
    "m": lambda d: (d.minute, 0),
    "mm": lambda d: (d.minute, 2),
    "h": lambda d: (d.hour % 12 or 12, 0),
    "hh": lambda d: (d.hour % 12 or 12, 2),
    "H": lambda d: (d.hour, 0),
    "HH": lambda d: (d.hour, 2),
    "d": lambda d: (d.day, 0),
    "dd": lambda d: (d.day, 2),
    "c": lambda d: (d.weekday, 0),
    "E": lambda d: (d.weekday, 0),
    "L": lambda d: (d.month, 0),
    "LL": lambda d: (d.month, 2),
    "M": lambda d: (d.month, 0),
    "MM": lambda d: (d.month, 2),
    "y": lambda d: (d.year, 0),
    "yy": lambda d: (int(str(d.year)[-2:]), 2),
    "yyyy": lambda d: (d.year, 4),
    "yyyyyy": lambda d: (d.year, 6),
    "kk": lambda d: (int(str(d.week_year)[-2:]), 2),
    "kkkk": lambda d: (d.week_year, 4),
    "W": lambda d: (d.week_number, 0),
    "WW": lambda d: (d.week_number, 2),
    "n": lambda d: (d.week_number, 0),
    "nn": lambda d: (d.week_number, 2),
    "ii": lambda d: (int(str(d.week_year)[-2:]), 2),
    "iiii": lambda d: (d.week_year, 4),
    "o": lambda d: (d.ordinal, 0),
    "ooo": lambda d: (d.ordinal, 3),
    "q": lambda d: (d.quarter, 0),
    "qq": lambda d: (d.quarter, 2),
    "X": lambda d: (d.ts // 1000, 0),
    "x": lambda d: (d.ts, 0),
}

# The en-US output of the Intl formats behind Luxon's macro tokens.
_MACROS = {
    "D": "M/d/yyyy",
    "DD": "MMM d, yyyy",
    "DDD": "MMMM d, yyyy",
    "DDDD": "EEEE, MMMM d, yyyy",
    "t": "h:mm a",
    "tt": "h:mm:ss a",
    "ttt": "h:mm:ss a ZZZZ",
    "tttt": "h:mm:ss a ZZZZZ",
    "T": "HH:mm",
    "TT": "HH:mm:ss",
    "TTT": "HH:mm:ss ZZZZ",
    "TTTT": "HH:mm:ss ZZZZZ",
    "f": "M/d/yyyy, h:mm a",
    "ff": "MMM d, yyyy, h:mm a",
    "fff": "MMMM d, yyyy 'at' h:mm a ZZZZ",
    "ffff": "EEEE, MMMM d, yyyy 'at' h:mm a ZZZZZ",
    "F": "M/d/yyyy, h:mm:ss a",
    "FF": "MMM d, yyyy, h:mm:ss a",
    "FFF": "MMMM d, yyyy 'at' h:mm:ss a ZZZZ",
    "FFFF": "EEEE, MMMM d, yyyy 'at' h:mm:ss a ZZZZZ",
}


def format_offset(offset: int, fmt: str) -> str:
    """Format an offset in minutes as ``+5`` (narrow), ``+05:00`` (short) or ``+0500`` (techie)."""
    hours = abs(offset) // 60
    minutes = abs(offset) % 60
    sign = "+" if offset >= 0 else "-"
    if fmt == "short":
        return f"{sign}{hours:02d}:{minutes:02d}"
    if fmt == "narrow":
        return f"{sign}{hours}" + (f":{minutes}" if minutes > 0 else "")
    return f"{sign}{hours:02d}{minutes:02d}"


def _offset_name(dt: DateTime, *, long: bool) -> str:
    if dt.o == 0:
        return "Coordinated Universal Time" if long else "UTC"
    return "GMT" + format_offset(dt.o, "narrow")


def _local_zone_name() -> str:
    return datetime.datetime.now().astimezone().tzname() or "local"


def parse_format(fmt: str) -> list[tuple[bool, str]]:
    """Split a Luxon format into ``(literal, text)`` runs, like ``Formatter.parseFormat``."""
    current: str | None = None
    current_full = ""
    bracketed = False
    splits: list[tuple[bool, str]] = []
    for c in fmt:
        if c == "'":
            if current_full:
                splits.append((bracketed or current_full.isspace(), current_full))
            current = None
            current_full = ""
            bracketed = not bracketed
        elif bracketed or c == current:
            current_full += c
        else:
            if current_full:
                splits.append((current_full.isspace(), current_full))
            current_full = c
            current = c
    if current_full:
        splits.append((bracketed or current_full.isspace(), current_full))
    return splits


##############
# Diff       #
##############


def _day_diff(earlier: DateTime, later: DateTime) -> int:
    def utc_day_start(dt: DateTime) -> int:
        c = dt.wall
        return _wall_ms(datetime.datetime(c.year, c.month, c.day))

    ms = utc_day_start(later) - utc_day_start(earlier)
    return math.floor(ms / 86_400_000)


_DIFFERS = (
    ("years", lambda a, b: b.year - a.year),
    ("quarters", lambda a, b: b.quarter - a.quarter + (b.year - a.year) * 4),
    ("months", lambda a, b: b.month - a.month + (b.year - a.year) * 12),
    ("weeks", lambda a, b: math.trunc(_day_diff(a, b) / 7)),
    ("days", _day_diff),
)


def _diff(earlier: DateTime, later: DateTime, units: list[str]) -> Duration:
    results: dict[str, float] = {}
    cursor = earlier
    lowest = None
    high_water = earlier
    for unit, differ in _DIFFERS:
        if unit not in units:
            continue
        lowest = unit
        results[unit] = differ(cursor, later)
        high_water = earlier.plus(Duration(results))
        if high_water.ts > later.ts:
            results[unit] -= 1
            cursor = earlier.plus(Duration(results))
            if cursor.ts > later.ts:
                high_water = cursor
                results[unit] -= 1
                cursor = earlier.plus(Duration(results))
        else:
            cursor = high_water
    remaining = later.ts - cursor.ts
    lower = [u for u in units if u in ("hours", "minutes", "seconds", "milliseconds")]
    if not lower and lowest is not None:
        if high_water.ts < later.ts:
            high_water = cursor.plus({lowest: 1})
        if high_water.ts != cursor.ts:
            results[lowest] = results.get(lowest, 0) + remaining / (high_water.ts - cursor.ts)
    duration = Duration(results)
    if lower:
        return Duration({"milliseconds": remaining}).shift_to(*lower).plus(duration)
    return duration


##############
# Duration   #
##############

ORDERED_UNITS = (
    "years",
    "quarters",
    "months",
    "weeks",
    "days",
    "hours",
    "minutes",
    "seconds",
    "milliseconds",
)

_LOW_ORDER = {
    "weeks": {
        "days": 7,
        "hours": 7 * 24,
        "minutes": 7 * 24 * 60,
        "seconds": 7 * 24 * 60 * 60,
        "milliseconds": 7 * 24 * 60 * 60 * 1000,
    },
    "days": {"hours": 24, "minutes": 24 * 60, "seconds": 24 * 60 * 60, "milliseconds": 86_400_000},
    "hours": {"minutes": 60, "seconds": 60 * 60, "milliseconds": 60 * 60 * 1000},
    "minutes": {"seconds": 60, "milliseconds": 60 * 1000},
    "seconds": {"milliseconds": 1000},
}

#: Luxon's casual conversion matrix.
MATRIX: dict[str, dict[str, float]] = {
    "years": {
        "quarters": 4,
        "months": 12,
        "weeks": 52,
        "days": 365,
        "hours": 365 * 24,
        "minutes": 365 * 24 * 60,
        "seconds": 365 * 24 * 60 * 60,
        "milliseconds": 365 * 24 * 60 * 60 * 1000,
    },
    "quarters": {
        "months": 3,
        "weeks": 13,
        "days": 91,
        "hours": 91 * 24,
        "minutes": 91 * 24 * 60,
        "seconds": 91 * 24 * 60 * 60,
        "milliseconds": 91 * 24 * 60 * 60 * 1000,
    },
    "months": {
        "weeks": 4,
        "days": 30,
        "hours": 30 * 24,
        "minutes": 30 * 24 * 60,
        "seconds": 30 * 24 * 60 * 60,
        "milliseconds": 30 * 24 * 60 * 60 * 1000,
    },
    **_LOW_ORDER,
}


def _js_mod(a: float, b: float) -> float:
    return math.fmod(a, b)


def _clean(value: float) -> float:
    """Ints stay ints, so that ``2 days`` does not become ``2.0 days``."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


@dataclass(frozen=True)
class Duration:
    """A length of time in calendar and clock units, like Luxon's ``Duration``."""

    values: dict[str, float]

    UNITS: ClassVar[tuple[str, ...]] = ORDERED_UNITS

    def __init__(self, values: dict[str, float] | None = None) -> None:
        clean: dict[str, float] = {}
        for unit, value in (values or {}).items():
            clean[normalize_unit(unit)] = _clean(value)
        ordered = {u: clean[u] for u in ORDERED_UNITS if u in clean}
        object.__setattr__(self, "values", ordered)

    def __hash__(self) -> int:
        return hash(self.to_millis())

    def get(self, unit: str) -> float:
        return self.values.get(normalize_unit(unit), 0)

    def to_millis(self) -> float:
        """Milliseconds, with a month as 30 days and a year as 365 days."""
        return _duration_to_millis(self.values)

    def as_unit(self, unit: str) -> float:
        return self.shift_to(unit).get(unit)

    def plus(self, other: Duration | dict) -> Duration:
        if isinstance(other, dict):
            other = Duration(other)
        result = {}
        for unit in ORDERED_UNITS:
            if unit in other.values or unit in self.values:
                result[unit] = other.get(unit) + self.get(unit)
        return Duration(result)

    def minus(self, other: Duration | dict) -> Duration:
        if isinstance(other, dict):
            other = Duration(other)
        return self.plus(other.negate())

    def negate(self) -> Duration:
        return Duration({u: -v if v else 0 for u, v in self.values.items()})

    def map_units(self, fn: object) -> Duration:
        return Duration({u: fn(v) for u, v in self.values.items()})  # type: ignore[operator]

    def shift_to(self, *units: str) -> Duration:
        """Express the duration in the given units, like Luxon's ``shiftTo``."""
        if not units:
            return self
        wanted = [normalize_unit(u) for u in units]
        built: dict[str, float] = {}
        accumulated: dict[str, float] = {}
        vals = dict(self.values)
        last_unit = wanted[0]
        for k in ORDERED_UNITS:
            if k in wanted:
                last_unit = k
                own = 0.0
                for ak in list(accumulated):
                    own += MATRIX[ak][k] * accumulated[ak]
                    accumulated[ak] = 0
                if k in vals:
                    own += vals[k]
                i = math.trunc(own)
                built[k] = i
                accumulated[k] = (own * 1000 - i * 1000) / 1000
            elif k in vals:
                accumulated[k] = vals[k]
        for key, value in accumulated.items():
            if value != 0:
                built[last_unit] += value if key == last_unit else value / MATRIX[last_unit][key]
        _normalize_values(built)
        return Duration(built)

    def shift_to_all(self) -> Duration:
        return self.shift_to(
            "years", "months", "weeks", "days", "hours", "minutes", "seconds", "milliseconds"
        )

    def normalize(self) -> Duration:
        vals = dict(self.values)
        _normalize_values(vals)
        return Duration(vals)

    def equals(self, other: object) -> bool:
        if not isinstance(other, Duration):
            return False
        return all((self.values.get(u) or 0) == (other.values.get(u) or 0) for u in ORDERED_UNITS)

    def __eq__(self, other: object) -> bool:
        return self.equals(other)

    def __repr__(self) -> str:
        return f"Duration({self.values})"

    def to_human(self) -> str:
        """English text like ``1 week, 3 days`` (Luxon ``toHuman``, Intl ``en`` narrow list)."""
        parts = []
        for unit in ORDERED_UNITS:
            if unit not in self.values:
                continue
            value = self.values[unit]
            singular = unit[:-1]
            word = singular if _plural_one(value) else unit
            parts.append(f"{format_number(value)} {word}")
        return ", ".join(parts)

    def to_format(self, fmt: str) -> str:
        """Format with ``y M w d h m s S`` tokens, like Luxon's ``Duration.toFormat``."""
        tokens = parse_format(fmt)
        fields = [
            _DUR_FIELD[val[0]] for literal, val in tokens if not literal and val[0] in _DUR_FIELD
        ]
        collapsed = self.shift_to(*fields) if fields else self
        out = []
        for literal, val in tokens:
            if literal or val[0] not in _DUR_FIELD:
                out.append(val)
                continue
            value = math.floor(collapsed.get(_DUR_FIELD[val[0]]))
            out.append(_num(value, len(val)))
        return "".join(out)


_DUR_FIELD = {
    "S": "milliseconds",
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
    "M": "months",
    "y": "years",
}


def _plural_one(value: float) -> bool:
    return value in (1, -1) and float(value).is_integer()


def format_number(value: float) -> str:
    """``Intl.NumberFormat("en-US")``: grouping commas, at most three fraction digits."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "NaN" if math.isnan(value) else ("-∞" if value < 0 else "∞")
    rounded = round(value, 3)
    if float(rounded).is_integer():
        return f"{int(rounded):,}"
    text = f"{rounded:,.3f}".rstrip("0").rstrip(".")
    return "-0" if text == "-0" else text


def _duration_to_millis(vals: dict[str, float]) -> float:
    total = vals.get("milliseconds", 0)
    for unit in reversed(ORDERED_UNITS[:-1]):
        if vals.get(unit):
            total += vals[unit] * MATRIX[unit]["milliseconds"]
    return total


def _normalize_values(vals: dict[str, float]) -> None:
    factor = -1 if _duration_to_millis(vals) < 0 else 1
    previous = None
    for current in reversed(ORDERED_UNITS):
        if current not in vals:
            continue
        if previous is not None:
            previous_val = vals[previous] * factor
            conv = MATRIX[current][previous]
            roll_up = math.floor(previous_val / conv)
            vals[current] += roll_up * factor
            vals[previous] -= roll_up * conv * factor
        previous = current
    previous = None
    for current in ORDERED_UNITS:
        if current not in vals:
            continue
        if previous is not None:
            fraction = _js_mod(vals[previous], 1)
            vals[previous] -= fraction
            vals[current] += fraction * MATRIX[previous][current]
        previous = current
    for unit, value in vals.items():
        vals[unit] = _clean(round(value, 9) if isinstance(value, float) else value)


##############
# fromFormat #
##############

_PARSE_TOKENS: dict[str, tuple[str, str]] = {
    "yyyy": (r"\d{4}", "year"),
    "yyyyy": (r"\d{4,6}", "year"),
    "yyyyyy": (r"\d{6}", "year"),
    "yy": (r"\d{2}", "year2"),
    "y": (r"\d{1,6}", "year"),
    "MM": (r"\d{2}", "month"),
    "M": (r"\d{1,2}", "month"),
    "LL": (r"\d{2}", "month"),
    "L": (r"\d{1,2}", "month"),
    "MMM": (r"[A-Za-z]{3}", "month_short"),
    "LLL": (r"[A-Za-z]{3}", "month_short"),
    "MMMM": (r"[A-Za-z]+", "month_long"),
    "LLLL": (r"[A-Za-z]+", "month_long"),
    "dd": (r"\d{2}", "day"),
    "d": (r"\d{1,2}", "day"),
    "o": (r"\d{1,3}", "ordinal"),
    "ooo": (r"\d{3}", "ordinal"),
    "HH": (r"\d{2}", "hour"),
    "H": (r"\d{1,2}", "hour"),
    "hh": (r"\d{2}", "hour12"),
    "h": (r"\d{1,2}", "hour12"),
    "mm": (r"\d{2}", "minute"),
    "m": (r"\d{1,2}", "minute"),
    "ss": (r"\d{2}", "second"),
    "s": (r"\d{1,2}", "second"),
    "SSS": (r"\d{3}", "millisecond"),
    "S": (r"\d{1,3}", "millisecond"),
    "u": (r"\d+", "fraction"),
    "a": (r"[AaPp][Mm]", "meridiem"),
    "EEE": (r"[A-Za-z]{3}", "ignore"),
    "EEEE": (r"[A-Za-z]+", "ignore"),
    "ccc": (r"[A-Za-z]{3}", "ignore"),
    "cccc": (r"[A-Za-z]+", "ignore"),
    "E": (r"\d", "ignore"),
    "c": (r"\d", "ignore"),
    "Z": (r"[+-]\d{1,2}(?::?\d{2})?|Z", "offset"),
    "ZZ": (r"[+-]\d{2}:\d{2}|Z", "offset"),
    "ZZZ": (r"[+-]\d{4}|Z", "offset"),
    "z": (r"[A-Za-z_]+(?:/[A-Za-z_+-]+)*", "zone"),
    "X": (r"-?\d+", "seconds_epoch"),
    "x": (r"-?\d+", "millis_epoch"),
}


def from_format(text: str, fmt: str) -> DateTime | None:
    """Parse ``text`` with Luxon format tokens. Returns None when it does not match."""
    pattern = ""
    fields: list[str] = []
    for literal, val in parse_format(fmt):
        token = _PARSE_TOKENS.get(val) if not literal else None
        if token is None:
            pattern += re.escape(val)
            continue
        pattern += f"({token[0]})"
        fields.append(token[1])
    m = re.fullmatch(pattern, text, re.IGNORECASE)
    if not m:
        return None
    now = DateTime.now()
    parts: dict[str, int] = {}
    zone: Zone = LOCAL
    meridiem = None
    for field_name, raw in zip(fields, m.groups(), strict=True):
        if field_name == "year2":
            year = int(raw)
            parts["year"] = 2000 + year if year < 60 else 1900 + year
        elif field_name == "month_short":
            names = [n.lower() for n in MONTHS_SHORT]
            if raw.lower() not in names:
                return None
            parts["month"] = names.index(raw.lower()) + 1
        elif field_name == "month_long":
            names = [n.lower() for n in MONTHS_LONG]
            if raw.lower() not in names:
                return None
            parts["month"] = names.index(raw.lower()) + 1
        elif field_name == "hour12":
            parts["hour"] = int(raw) % 12
        elif field_name == "meridiem":
            meridiem = raw.lower()
        elif field_name == "fraction":
            parts["millisecond"] = int((raw + "000")[:3])
        elif field_name == "offset":
            zone = UTC if raw.upper() == "Z" else _offset_zone(raw)
        elif field_name == "zone":
            try:
                zone = parse_zone(raw)
            except InvalidDateError:
                return None
        elif field_name == "seconds_epoch":
            return DateTime(int(raw) * 1000, LOCAL)
        elif field_name == "millis_epoch":
            return DateTime(int(raw), LOCAL)
        elif field_name != "ignore":
            parts[field_name] = int(raw)
    if meridiem == "pm" and "hour" in parts:
        parts["hour"] += 12
    if "ordinal" in parts:
        year = parts.get("year", now.year)
        day = datetime.date(year, 1, 1) + datetime.timedelta(days=parts.pop("ordinal") - 1)
        parts.update(year=day.year, month=day.month, day=day.day)
    # Missing higher units come from now, lower ones are their minimum.
    order = ("year", "month", "day", "hour", "minute", "second", "millisecond")
    highest = next((i for i, u in enumerate(order) if u in parts), len(order))
    values = {}
    for i, unit in enumerate(order):
        if unit in parts:
            values[unit] = parts[unit]
        elif i < highest:
            values[unit] = getattr(now, unit)
        else:
            values[unit] = 1 if unit in ("month", "day") else 0
    try:
        wall_dt = DateTime.from_object(**values, zone=zone)
    except InvalidDateError:
        return None
    return wall_dt.set_zone(LOCAL)


def _offset_zone(raw: str) -> Zone:
    sign = -1 if raw.startswith("-") else 1
    digits = raw[1:].replace(":", "")
    hours = int(digits[:2]) if len(digits) >= 2 else int(digits)
    minutes = int(digits[2:4]) if len(digits) >= 4 else 0
    return FixedZone(sign * (hours * 60 + minutes))
