"""Diagnose & fix native dependencies (GTK/Pango/Cairo) and pandoc.

Pure diagnosis is read-only. ``apply_fix`` shells out to the platform's
package manager — apt/dnf/pacman/zypper/apk on Linux, brew on macOS, winget
on Windows. All binaries come from the upstream/vendor repositories of those
package managers; this project hosts none of its own.

The fix command is always printed before execution and gated by a confirm
prompt unless ``assume_yes`` is set.
"""

from __future__ import annotations

import ctypes.util
import shutil
import subprocess
import sys
from dataclasses import dataclass
from dataclasses import field

from obsidian_pdf_exporter.runtime import register_native_dependencies

# Libs WeasyPrint links against at runtime. Names match what
# ``ctypes.util.find_library`` accepts (it strips lib*/.so.N per platform).
_REQUIRED_LIBS: tuple[str, ...] = (
    "gobject-2.0",
    "pango-1.0",
    "pangoft2-1.0",
    "cairo",
    "harfbuzz",
)


@dataclass
class Diagnosis:
    """Snapshot of native-dep state on this machine."""

    platform: str
    missing_libs: list[str] = field(default_factory=list)
    pandoc_present: bool = False
    package_manager: str | None = None
    fix_command: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True iff nothing needs fixing (pandoc may auto-download lazily)."""
        return not self.missing_libs


def diagnose() -> Diagnosis:
    """Probe runtime libs and pandoc. Read-only."""
    register_native_dependencies()

    d = Diagnosis(platform=sys.platform)
    d.missing_libs = [lib for lib in _REQUIRED_LIBS if ctypes.util.find_library(lib) is None]
    d.pandoc_present = shutil.which("pandoc") is not None or _pypandoc_has_pandoc()

    if sys.platform.startswith("linux"):
        d.package_manager, d.fix_command, d.notes = _linux_plan(d.missing_libs)
    elif sys.platform == "darwin":
        d.package_manager, d.fix_command, d.notes = _macos_plan(d.missing_libs)
    elif sys.platform == "win32":
        d.package_manager, d.fix_command, d.notes = _windows_plan(d.missing_libs)
    return d


def apply_fix(d: Diagnosis, *, assume_yes: bool = False) -> int:
    """Run the fix plan. Returns process exit code (0 = success, 130 = aborted)."""
    if d.ok:
        return 0
    if d.fix_command is None:
        return 1

    if not assume_yes:
        print(f"Will run: {d.fix_command}")  # noqa: T201
        if input("Proceed? [y/N] ").strip().lower() not in {"y", "yes"}:
            return 130

    if d.platform == "win32":
        return subprocess.call(["cmd.exe", "/c", d.fix_command])  # noqa: S603,S607
    return subprocess.call(["/bin/sh", "-c", d.fix_command])  # noqa: S603


# --- Linux -----------------------------------------------------------------

# (install-cmd template, lib -> distro package name overrides). Libs not in
# the override map fall through to their canonical name.
_LINUX_PKG_MAP: dict[str, tuple[str, dict[str, str]]] = {
    "apt": (
        "sudo apt-get update && sudo apt-get install -y {pkgs}",
        {
            "gobject-2.0": "libglib2.0-0",
            "pango-1.0": "libpango-1.0-0",
            "pangoft2-1.0": "libpangoft2-1.0-0",
            "cairo": "libcairo2",
            "harfbuzz": "libharfbuzz0b",
        },
    ),
    "dnf": (
        "sudo dnf install -y {pkgs}",
        {"gobject-2.0": "glib2", "pango-1.0": "pango", "pangoft2-1.0": "pango"},
    ),
    "pacman": (
        "sudo pacman -S --needed --noconfirm {pkgs}",
        {"gobject-2.0": "glib2", "pango-1.0": "pango", "pangoft2-1.0": "pango"},
    ),
    "zypper": (
        "sudo zypper install -y {pkgs}",
        {"gobject-2.0": "glib2", "pango-1.0": "pango", "pangoft2-1.0": "pango"},
    ),
    "apk": (
        "sudo apk add {pkgs}",
        {"gobject-2.0": "glib", "pango-1.0": "pango", "pangoft2-1.0": "pango"},
    ),
}


def _linux_plan(missing: list[str]) -> tuple[str | None, str | None, list[str]]:
    pm = _detect_linux_pm()
    if pm is None:
        return None, None, ["No supported package manager found (apt/dnf/pacman/zypper/apk)."]
    if not missing:
        return pm, None, []
    template, lib_to_pkg = _LINUX_PKG_MAP[pm]
    pkgs = sorted({lib_to_pkg.get(lib, lib) for lib in missing})
    return (
        pm,
        template.format(pkgs=" ".join(pkgs)),
        ["Requires sudo. Command shown verbatim before execution."],
    )


def _detect_linux_pm() -> str | None:
    for pm in ("apt", "dnf", "pacman", "zypper", "apk"):
        if shutil.which(pm) is not None:
            return pm
    return None


# --- macOS -----------------------------------------------------------------


def _macos_plan(missing: list[str]) -> tuple[str | None, str | None, list[str]]:
    has_brew = shutil.which("brew") is not None
    if not missing:
        return ("brew" if has_brew else None), None, []
    if not has_brew:
        return (
            None,
            None,
            ["Install Homebrew (https://brew.sh), then re-run `ope doctor --fix`."],
        )
    return "brew", "brew install pango", []


# --- Windows ---------------------------------------------------------------


def _windows_plan(missing: list[str]) -> tuple[str | None, str | None, list[str]]:
    if not missing:
        return None, None, []
    if shutil.which("winget") is None:
        return (
            None,
            None,
            [
                "winget not found. Install from the Microsoft Store (App Installer),",
                "or install GTK3 manually from",
                "https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases",
                "or install Inkscape (https://inkscape.org), which bundles GTK.",
            ],
        )
    return (
        "winget",
        "winget install --id tschoonj.GTK3 --accept-source-agreements --accept-package-agreements",
        [
            "Installs the GTK3 runtime from the upstream GitHub release via winget.",
            "Default install path C:\\Program Files\\GTK3-Runtime Win64\\bin is auto-discovered.",
        ],
    )


# --- helpers ---------------------------------------------------------------


def _pypandoc_has_pandoc() -> bool:
    try:
        import pypandoc

        pypandoc.get_pandoc_path()
    except (ImportError, OSError):
        return False
    return True
