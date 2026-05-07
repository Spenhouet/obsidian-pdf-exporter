"""Template discovery and registration.

Templates can come from four sources, each shown in ``list-templates``:

- ``builtin`` / ``entry-point`` — registered via the
  ``obsidian_pdf_exporter.templates`` entry point group in
  ``pyproject.toml``. Built-ins are entry points that resolve to a class
  inside this package.
- ``user-config`` — a directory in the user-config templates folder
  (``$OBSIDIAN_PDF_EXPORTER_TEMPLATES_DIR`` or
  ``$XDG_CONFIG_HOME/obsidian-pdf-exporter/templates``, defaulting to
  ``~/.config/obsidian-pdf-exporter/templates``). Each subdirectory is
  one template, loaded by :class:`FilesystemTemplate`.
- ``runtime`` — registered programmatically via :func:`register_template`
  by an embedding application.

Resolution order in :func:`resolve_template` for ``--template <value>``:

1. If ``value`` exists as a file or directory, load it as a filesystem
   template.
2. Otherwise, look the value up in the merged registry (entry-point →
   user-config → runtime, last wins).
"""

from __future__ import annotations

import os
import warnings
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.templates.filesystem import load_from_path

if TYPE_CHECKING:
    from obsidian_pdf_exporter.templates.base import Template


_ENTRY_POINT_GROUP = "obsidian_pdf_exporter.templates"
_BUILTIN_PACKAGE = "obsidian_pdf_exporter.templates.builtin"
_USER_DIR_ENV = "OBSIDIAN_PDF_EXPORTER_TEMPLATES_DIR"

#: Source label attached to discovered templates and shown by ``list-templates``.
SOURCE_BUILTIN = "builtin"
SOURCE_ENTRY_POINT = "entry-point"
SOURCE_USER_CONFIG = "user-config"
SOURCE_RUNTIME = "runtime"

_RUNTIME_REGISTRY: dict[str, type[Template] | Template] = {}


def register_template(
    template: type[Template] | Template,
    name: str | None = None,
) -> None:
    """Register a template so it can be loaded by name.

    Args:
        template: A :class:`Template` subclass or an already-instantiated
            template instance.
        name: Override the registration key. Defaults to ``template.name``.
    """
    key = name or getattr(template, "name", None)
    if not key:
        msg = "Template must define a non-empty .name attribute or be registered with one"
        raise ValueError(msg)
    _RUNTIME_REGISTRY[key] = template


def user_templates_dir() -> Path:
    """Return the directory where named user templates are auto-discovered."""
    env = os.environ.get(_USER_DIR_ENV)
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "obsidian-pdf-exporter" / "templates"


def available_templates() -> dict[str, Template]:
    """Return all known templates as instances, keyed by registration name."""
    return {name: tpl for name, (tpl, _src) in _discover().items()}


def template_sources() -> dict[str, str]:
    """Return ``name -> source`` for every available template.

    The source string is one of :data:`SOURCE_BUILTIN`,
    :data:`SOURCE_ENTRY_POINT`, :data:`SOURCE_USER_CONFIG`,
    :data:`SOURCE_RUNTIME`. User-config sources include the directory in
    parentheses for a useful ``list-templates`` display.
    """
    return {name: src for name, (_tpl, src) in _discover().items()}


def load_template(name: str) -> Template:
    """Look up and return a template by name from the merged registry.

    Raises:
        KeyError: If no template with that name is registered.
    """
    discovered = _discover()
    if name not in discovered:
        known = ", ".join(sorted(discovered)) or "(none)"
        msg = f"Unknown template {name!r}. Available templates: {known}"
        raise KeyError(msg)
    return discovered[name][0]


def resolve_template(value: str) -> Template:
    """Resolve a CLI ``--template`` value to a :class:`Template` instance.

    Filesystem paths take precedence over registry names, so
    ``--template ./brand.css`` always loads the file even if a registered
    template happens to share the stem.

    Raises:
        KeyError: If neither path nor name resolves.
    """
    path = Path(value).expanduser()
    if path.exists():
        return load_from_path(path)
    return load_template(value)


def _discover() -> dict[str, tuple[Template, str]]:
    out: dict[str, tuple[Template, str]] = {}

    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
            instance = cls() if isinstance(cls, type) else cls
        except Exception as exc:  # noqa: BLE001 - one broken plugin must not break the rest
            warnings.warn(
                f"Failed to load template plugin {ep.name!r}: {exc}",
                stacklevel=2,
            )
            continue
        module = getattr(cls, "__module__", "") if isinstance(cls, type) else ""
        source = SOURCE_BUILTIN if module.startswith(_BUILTIN_PACKAGE) else SOURCE_ENTRY_POINT
        out[ep.name] = (instance, source)

    user_dir = user_templates_dir()
    if user_dir.is_dir():
        for entry in sorted(user_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            try:
                tpl = load_from_path(entry)
            except Exception as exc:  # noqa: BLE001 - skip a single broken dir
                warnings.warn(
                    f"Failed to load user template at {entry}: {exc}",
                    stacklevel=2,
                )
                continue
            out[tpl.name] = (tpl, f"{SOURCE_USER_CONFIG} ({entry})")

    for name, value in _RUNTIME_REGISTRY.items():
        instance = value() if isinstance(value, type) else value
        out[name] = (instance, SOURCE_RUNTIME)

    return out
