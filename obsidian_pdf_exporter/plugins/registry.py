"""Discover and instantiate Obsidian plugin support modules.

Plugins are normally registered via the
``obsidian_pdf_exporter.obsidian_plugins`` entry point group in
``pyproject.toml``::

    [project.entry-points."obsidian_pdf_exporter.obsidian_plugins"]
    tasks = "my_obsidian_tasks_plugin:TasksPlugin"

External integrations can also register a plugin at runtime via
:func:`register_plugin`.
"""

from __future__ import annotations

import warnings
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from obsidian_pdf_exporter.plugins.base import ObsidianPlugin

_ENTRY_POINT_GROUP = "obsidian_pdf_exporter.obsidian_plugins"
_RUNTIME_REGISTRY: dict[str, type[ObsidianPlugin]] = {}


def register_plugin(plugin_cls: type[ObsidianPlugin], name: str | None = None) -> None:
    """Register an :class:`ObsidianPlugin` subclass so it can be loaded by name."""
    key = name or getattr(plugin_cls, "name", None)
    if not key:
        msg = "ObsidianPlugin must define a non-empty .name attribute or be registered with one"
        raise ValueError(msg)
    _RUNTIME_REGISTRY[key] = plugin_cls


def available_plugins() -> dict[str, type[ObsidianPlugin]]:
    """Return all registered plugin classes (entry-point + runtime)."""
    found: dict[str, type[ObsidianPlugin]] = {}
    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        try:
            found[ep.name] = ep.load()
        except Exception as exc:  # noqa: BLE001 - one broken plugin must not break the rest
            warnings.warn(
                f"Failed to load Obsidian plugin {ep.name!r}: {exc}",
                stacklevel=2,
            )
    found.update(_RUNTIME_REGISTRY)
    return found


def active_plugins(disabled: set[str] | None = None) -> list[ObsidianPlugin]:
    """Instantiate every available plugin (excluding ``disabled``), sorted by priority."""
    excluded = disabled or set()
    instances: list[ObsidianPlugin] = []
    for name, cls in available_plugins().items():
        if name in excluded:
            continue
        try:
            instances.append(cls())
        except Exception as exc:  # noqa: BLE001 - skip plugins whose constructor blows up
            warnings.warn(
                f"Failed to instantiate Obsidian plugin {name!r}: {exc}",
                stacklevel=2,
            )
    instances.sort(key=lambda p: (p.priority, p.name))
    return instances
