"""Map the Mermaid theme of a diagram to Pele.

Pele does not read Mermaid's ``themeVariables``. It draws with a few CSS
variables (``--pele-surface``, ``--pele-border``, ...) and gives its elements
class names such as ``pele-task`` or ``pele-quadrant``. ope maps every theme
variable that has a counterpart in Pele's drawing:

* to a ``--pele-*`` variable of that diagram, when Pele uses the variable for
  exactly what the theme variable colors, or
* to a CSS rule for Pele's class names, which ope writes into the SVG. The
  rules only set colors, opacity and stroke width, never sizes, so the layout
  Pele made with the measured text widths stays valid.

:data:`SUPPORTED` lists the theme variables per diagram type, and the docs
page ``docs/obsidian/mermaid.md`` shows the same table. :func:`unused_keys`
returns the keys of a Mermaid config that have no effect, so the export can
warn about them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Number of series colors Pele has, ``--pele-series-1`` to ``--pele-series-8``.
SERIES = 8


@dataclass(frozen=True)
class _Rule:
    """A CSS declaration whose value is the first theme variable of ``keys`` that is set."""

    selector: str
    prop: str
    keys: tuple[str, ...]
    #: Extra declarations written with the rule, such as ``fill-opacity: 1``.
    extra: str = ""
    #: Value written instead of the theme variable's, when one of ``keys`` is set.
    fixed: str = ""


@dataclass(frozen=True)
class _Spec:
    """How the theme variables of one diagram type map to Pele."""

    #: ``--pele-*`` variable to the theme variables that set it, first one wins.
    variables: dict[str, tuple[str, ...]]
    rules: tuple[_Rule, ...]


def _title(*keys: str) -> _Rule:
    return _Rule(".pele-title", "fill", (*keys, "titleColor"))


_TASK = ".pele-task"
#: A task that is not done, active or critical.
_PLAIN = ":not(.pele-done):not(.pele-crit):not(.pele-active)"
_SHAPES = ("rect", "path")


def _shapes(states: str, prop: str, keys: tuple[str, ...], extra: str = "") -> list[_Rule]:
    return [_Rule(f"{_TASK}{states} {shape}", prop, keys, extra) for shape in _SHAPES]


_GANTT = _Spec(
    variables={},
    rules=(
        _title(),
        *_shapes(_PLAIN, "fill", ("taskBkgColor",)),
        *_shapes(_PLAIN, "stroke", ("taskBorderColor",)),
        *_shapes(".pele-active", "fill", ("activeTaskBkgColor",), "fill-opacity: 1"),
        *_shapes(".pele-active:not(.pele-crit)", "stroke", ("activeTaskBorderColor",)),
        *_shapes(".pele-done", "fill", ("doneTaskBkgColor",)),
        *_shapes(".pele-done:not(.pele-crit)", "stroke", ("doneTaskBorderColor",)),
        *_shapes(".pele-crit:not(.pele-done):not(.pele-active)", "fill", ("critBkgColor",)),
        *_shapes(".pele-crit", "stroke", ("critBorderColor",)),
        _Rule(f"{_TASK} .ope-inside", "fill", ("taskTextColor",)),
        _Rule(f"{_TASK}.pele-done .ope-inside", "fill", ("taskTextDarkColor",)),
        _Rule(f"{_TASK}.pele-active .ope-inside", "fill", ("taskTextDarkColor",)),
        _Rule(f"{_TASK} .ope-outside", "fill", ("taskTextOutsideColor", "taskTextDarkColor")),
        _Rule(".pele-grid path", "stroke", ("gridColor",)),
        _Rule(".pele-section-0", "fill", ("sectionBkgColor",)),
        _Rule(".pele-section-1", "fill", ("altSectionBkgColor",), "fill-opacity: 0.2"),
        _Rule(".pele-section-2", "fill", ("sectionBkgColor2",)),
        _Rule(".pele-section-3", "fill", ("altSectionBkgColor",), "fill-opacity: 0.2"),
        _Rule(".pele-section-label", "fill", ("titleColor",)),
        _Rule(".pele-today path", "stroke", ("todayLineColor",)),
        _Rule(".pele-today path + path", "fill", ("todayLineColor",)),
        _Rule(".pele-excluded rect", "fill", ("excludeBkgColor",)),
        _Rule(".pele-vert", "stroke", ("vertLineColor",)),
    ),
)

_TIMELINE = _Spec(
    variables={f"--pele-series-{i + 1}": (f"cScale{i}",) for i in range(SERIES)},
    rules=(
        _title(),
        *(
            rule
            for i in range(SERIES)
            for rule in (
                _Rule(f".ope-series-{i + 1} text", "fill", (f"cScaleLabel{i}",)),
                _Rule(f".ope-series-{i + 1} .pele-event text", "fill", (f"cScaleLabel{i}",)),
                _Rule(
                    f".ope-series-{i + 1} .pele-event rect",
                    "fill-opacity",
                    (f"cScale{i}",),
                    "",
                    "1",
                ),
            )
        ),
    ),
)

_QUADRANT = _Spec(
    variables={},
    rules=(
        _title("quadrantTitleFill"),
        *(
            rule
            for i in range(1, 5)
            for rule in (
                _Rule(f'.pele-quadrant[data-id="{i}"] rect', "fill", (f"quadrant{i}Fill",)),
                _Rule(f'.pele-quadrant[data-id="{i}"] text', "fill", (f"quadrant{i}TextFill",)),
            )
        ),
        _Rule(
            ".pele-quadrant rect",
            "stroke",
            ("quadrantInternalBorderStrokeFill", "quadrantExternalBorderStrokeFill"),
        ),
        _Rule(".pele-point", "fill", ("quadrantPointFill",)),
        _Rule(".pele-point-labels text", "fill", ("quadrantPointTextFill",)),
        _Rule(".pele-axis-labels text", "fill", ("quadrantXAxisTextFill",)),
        _Rule(".pele-axis-labels g text", "fill", ("quadrantYAxisTextFill",)),
    ),
)

_PIE = _Spec(
    variables={},
    rules=(
        _title("pieTitleTextColor"),
        _Rule(".pele-slice", "stroke", ("pieStrokeColor",)),
        _Rule(".pele-slice", "stroke-width", ("pieStrokeWidth",)),
        _Rule(".pele-slice", "fill-opacity", ("pieOpacity",)),
        _Rule(".pele-slice-labels text", "fill", ("pieSectionTextColor",)),
        _Rule(".pele-legend text", "fill", ("pieLegendTextColor",)),
    ),
)


def _xy_axes(name: str) -> tuple[str, ...]:
    """Return the x and the y axis key of ``name``. Pele draws both axes in one color."""
    return (f"xyChart.xAxis{name}", f"xyChart.yAxis{name}")


_XYCHART = _Spec(
    variables={},
    rules=(
        _title("xyChart.titleColor"),
        _Rule(".pele-axis-labels text", "fill", _xy_axes("LabelColor")),
        _Rule(".pele-axis-titles text", "fill", _xy_axes("TitleColor")),
        _Rule(".pele-axis", "stroke", _xy_axes("LineColor")),
    ),
)

_FLOWCHART = _Spec(
    variables={
        "--pele-surface": ("mainBkg", "primaryColor"),
        "--pele-border": ("nodeBorder", "primaryBorderColor"),
    },
    rules=(
        _title(),
        _Rule(".pele-node .pele-label", "fill", ("nodeTextColor", "primaryTextColor")),
        _Rule(".pele-cluster rect", "fill", ("clusterBkg",), "fill-opacity: 1"),
        _Rule(".pele-cluster rect", "stroke", ("clusterBorder",)),
        _Rule(".pele-cluster-label", "fill", ("titleColor",)),
        _Rule(".pele-edge-label rect", "fill", ("edgeLabelBackground",)),
    ),
)

_ACTOR_BKG = ("actorBkg", "mainBkg", "primaryColor")
_ACTOR_BORDER = ("actorBorder", "primaryBorderColor")
_SEQUENCE = _Spec(
    variables={},
    rules=(
        _title(),
        _Rule(".pele-actor rect", "fill", _ACTOR_BKG),
        _Rule(".pele-actor circle", "fill", _ACTOR_BKG),
        _Rule(".pele-actor rect", "stroke", _ACTOR_BORDER),
        _Rule(".pele-actor circle", "stroke", _ACTOR_BORDER),
        _Rule(".pele-actor path", "stroke", _ACTOR_BORDER),
        _Rule(".pele-actor text", "fill", ("actorTextColor", "primaryTextColor")),
        _Rule(".pele-lifeline", "stroke", ("actorLineColor", *_ACTOR_BORDER)),
        _Rule(".pele-message path:not(.pele-marker)", "stroke", ("signalColor", "textColor")),
        _Rule(".pele-message .pele-marker", "fill", ("signalColor", "textColor")),
        _Rule(".pele-edge-label text", "fill", ("signalTextColor", "textColor")),
        _Rule(".pele-note rect", "fill", ("noteBkgColor",)),
        _Rule(".pele-note rect", "stroke", ("noteBorderColor",)),
        _Rule(".pele-note text", "fill", ("noteTextColor",)),
        _Rule(".pele-activation", "fill", ("activationBkgColor",)),
        _Rule(".pele-activation", "stroke", ("activationBorderColor",)),
        _Rule(".pele-frame rect", "stroke", ("labelBoxBorderColor", *_ACTOR_BORDER)),
        _Rule(".pele-frame rect + rect", "fill", ("labelBoxBkgColor", *_ACTOR_BKG)),
        _Rule(".pele-frame-kind", "fill", ("labelTextColor", "actorTextColor", "primaryTextColor")),
        _Rule(".pele-frame-label", "fill", ("loopTextColor", "actorTextColor", "primaryTextColor")),
    ),
)

_SPECS: dict[str, _Spec] = {
    "gantt": _GANTT,
    "timeline": _TIMELINE,
    "quadrantChart": _QUADRANT,
    "pie": _PIE,
    "xychart": _XYCHART,
    "xychart-beta": _XYCHART,
    "flowchart": _FLOWCHART,
    "flowchart-elk": _FLOWCHART,
    "sequenceDiagram": _SEQUENCE,
}

#: Variables every diagram takes from the theme, first theme variable that is set wins.
_COMMON: dict[str, tuple[str, ...]] = {
    "--pele-bg": ("background",),
    "--pele-fg": ("textColor", "primaryTextColor"),
    "--pele-line": ("lineColor",),
}

#: Theme variables handled elsewhere: the font, and the series colors of
#: :func:`obsidian_pdf_exporter.core.mermaid_pele.series_colors`.
_OTHER_KEYS = {
    "fontFamily",
    "fontSize",
    "xyChart.plotColorPalette",
    *(f"pie{i}" for i in range(1, SERIES + 1)),
}

#: Keys of the per-diagram config that Pele reads, by config section.
DIAGRAM_CONFIG: dict[str, set[str]] = {
    "gantt": {
        "barHeight",
        "barGap",
        "fontSize",
        "sectionFontSize",
        "numberSectionStyles",
        "leftPadding",
        "rightPadding",
        "topPadding",
        "gridLineStartPadding",
        "useWidth",
        "axisFormat",
        "tickInterval",
        "weekday",
        "topAxis",
        "displayMode",
    },
    "quadrantChart": {
        "chartWidth",
        "chartHeight",
        "pointRadius",
        "pointTextPadding",
        "quadrantPadding",
        "quadrantTextTopPadding",
        "titlePadding",
        "xAxisLabelPadding",
        "yAxisLabelPadding",
        "xAxisPosition",
        "yAxisPosition",
        "titleFontSize",
        "quadrantLabelFontSize",
        "xAxisLabelFontSize",
        "yAxisLabelFontSize",
        "pointLabelFontSize",
    },
    "xyChart": {
        "width",
        "height",
        "chartOrientation",
        "showDataLabel",
        "showLegend",
        "showTitle",
        "xAxis.showAxisLine",
        "xAxis.showLabel",
        "xAxis.showTick",
        "xAxis.showTitle",
        "yAxis.showAxisLine",
        "yAxis.showLabel",
        "yAxis.showTick",
        "yAxis.showTitle",
    },
    "timeline": {"disableMulticolor"},
    "pie": {"donutHole", "legendPosition", "textPosition"},
    "sequence": {
        "actorMargin",
        "boxMargin",
        "height",
        "width",
        "messageMargin",
        "noteMargin",
        "mirrorActors",
        "rightAngles",
        "messageAlign",
        "showSequenceNumbers",
        "hideUnusedParticipants",
    },
}
#: Keys of a per-diagram config section that only matter in a browser.
_BROWSER_KEYS = {"useMaxWidth", "htmlLabels"}

#: Values of ``theme`` that need no warning: ``base`` only exists to be
#: changed with ``themeVariables``.
_QUIET_THEMES = {"default", "base"}

_RE_SAFE_VALUE = re.compile(r"^[#(),.%\w\s-]+$")


def _all_keys(spec: _Spec) -> set[str]:
    keys = {k for chain in spec.variables.values() for k in chain}
    return keys | {k for rule in spec.rules for k in rule.keys}


#: Theme variables ope maps, per diagram type. Every type also uses the
#: variables of ``_COMMON``, ``titleColor``, ``fontFamily`` and ``fontSize``.
SUPPORTED: dict[str, set[str]] = {kind: _all_keys(spec) for kind, spec in _SPECS.items()}
SUPPORTED["pie"] |= {f"pie{i}" for i in range(1, SERIES + 1)}
SUPPORTED["xychart"] |= {"xyChart.plotColorPalette"}
SUPPORTED["xychart-beta"] = SUPPORTED["xychart"]

_KNOWN_KEYS = (
    {k for keys in SUPPORTED.values() for k in keys}
    | {k for chain in _COMMON.values() for k in chain}
    | _OTHER_KEYS
    | {"titleColor"}
)


def flat_theme(*configs: Mapping[str, Any]) -> dict[str, str]:
    """Return the ``themeVariables`` of ``configs`` as one flat dict, later ones win.

    Nested values, such as ``xyChart.titleColor``, get a dotted key.
    """
    out: dict[str, str] = {}
    for config in configs:
        theme_vars = config.get("themeVariables")
        if isinstance(theme_vars, dict):
            out.update(_flatten(theme_vars))
    return out


def _flatten(values: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in values.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, name + "."))
        elif value is not None and not isinstance(value, list):
            out[name] = str(value).strip()
    return out


def _value(theme: Mapping[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = theme.get(key)
        if value and _RE_SAFE_VALUE.match(value):
            return value.replace('"', "'")
    return None


def diagram_variables(kind: str, theme: Mapping[str, str]) -> dict[str, str]:
    """Return the ``--pele-*`` variables a diagram of type ``kind`` gets from ``theme``."""
    spec = _SPECS.get(kind)
    chains = {**_COMMON, **(spec.variables if spec else {})}
    out = {}
    for name, keys in chains.items():
        value = _value(theme, keys)
        if value:
            out[name] = value
    return out


def diagram_css(kind: str, theme: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """Return the CSS rules a diagram of type ``kind`` gets from ``theme``.

    Each rule is a selector and its declarations, such as
    ``(".pele-point", "fill: #c00")``.
    """
    spec = _SPECS.get(kind)
    rules = spec.rules if spec else (_title(),)
    out = []
    for rule in rules:
        value = _value(theme, rule.keys)
        if value is None:
            continue
        declarations = f"{rule.prop}: {rule.fixed or value}"
        if rule.extra:
            declarations += f"; {rule.extra}"
        out.append((rule.selector, declarations))
    return tuple(out)


def unused_keys(config: Mapping[str, Any]) -> list[str]:
    """Return the keys of a Mermaid config that have no effect when Pele draws.

    Covers ``theme``, ``themeCSS``, the ``themeVariables`` and the sections of
    the diagram types listed in :data:`DIAGRAM_CONFIG`.
    """
    out = []
    theme = config.get("theme")
    if isinstance(theme, str) and theme.strip().lower() not in _QUIET_THEMES:
        out.append("theme")
    if config.get("themeCSS"):
        out.append("themeCSS")
    out.extend(f"themeVariables.{key}" for key in flat_theme(config) if key not in _KNOWN_KEYS)
    for section, known in DIAGRAM_CONFIG.items():
        values = config.get(section)
        if not isinstance(values, dict):
            continue
        out.extend(
            f"{section}.{key}"
            for key in _flatten(values)
            if key not in known and key.split(".")[-1] not in _BROWSER_KEYS
        )
    return out


#: A gantt task: its group, its bar or diamond, and its label.
_RE_GANTT_TASK = re.compile(
    r'(<g class="pele-task[^"]*"[^>]*>)(<(rect|path)\b[^>]*>)(<text class="pele-label)"'
)
_RE_NUMBER_ATTR = r'\s{}="(-?[\d.]+)"'
#: A timeline period, by the series color of its box.
_RE_PERIOD = re.compile(
    r'<g class="pele-node pele-period"'
    r'(?P<rest>[^>]*><rect\b[^>]*fill="var\(--pele-series-(?P<n>\d+))'
)


def mark_svg(svg: str) -> str:
    """Add the class names the CSS of :func:`diagram_css` needs to a raw Pele SVG.

    A gantt label gets ``ope-inside`` when it is drawn on its bar and
    ``ope-outside`` otherwise. A timeline period gets ``ope-series-N`` for its
    color.
    """
    svg = _RE_GANTT_TASK.sub(_mark_task, svg)
    return _RE_PERIOD.sub(r'<g class="pele-node pele-period ope-series-\g<n>"\g<rest>', svg)


def _mark_task(m: re.Match[str]) -> str:
    group, shape, kind, text = m.group(1), m.group(2), m.group(3), m.group(4)
    inside = False
    if kind == "rect":
        rest = m.string[m.end() :]
        x = re.search(_RE_NUMBER_ATTR.format("x"), shape)
        width = re.search(_RE_NUMBER_ATTR.format("width"), shape)
        label_x = re.match(r"[^>]*?" + _RE_NUMBER_ATTR.format("x"), rest)
        if x and width and label_x:
            left = float(x.group(1))
            inside = left <= float(label_x.group(1)) <= left + float(width.group(1))
    where = "ope-inside" if inside else "ope-outside"
    return f'{group}{shape}{text} {where}"'
