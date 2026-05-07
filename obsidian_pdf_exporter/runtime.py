"""Runtime helpers: native library discovery, optional dependency probes."""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import sys
from pathlib import Path

GTK_PATH_ENV = "OBSIDIAN_PDF_GTK_PATH"

_PROBE_LIB = "gobject-2.0"

_PLATFORM_FALLBACKS: dict[str, tuple[str, ...]] = {
    "win32": (
        r"C:\Program Files\Inkscape\bin",
        r"C:\Program Files\GTK3-Runtime Win64\bin",
        r"C:\msys64\mingw64\bin",
        r"C:\msys64\ucrt64\bin",
        r"C:\GTK\bin",
    ),
    "darwin": (
        "/opt/homebrew/lib",  # Apple Silicon Homebrew
        "/usr/local/lib",  # Intel Homebrew
        "/opt/local/lib",  # MacPorts
    ),
}

_DARWIN_PRELOAD_ORDER = ("gobject-2.0", "pango-1.0", "pangoft2-1.0", "cairo", "harfbuzz")


def register_native_dependencies() -> None:
    """Make GTK/Pango/Cairo discoverable for WeasyPrint.

    No-op when the dynamic loader already finds the libs. Otherwise, per platform:
      * Linux: no-op — distro packages install to standard loader paths.
      * macOS: if the system loader already resolves GTK, no-op; otherwise
        preload libs from Homebrew/MacPorts directories via ``ctypes``.
      * Windows: register Inkscape/MSYS2/GTK install dirs with
        ``os.add_dll_directory``.

    Set ``OBSIDIAN_PDF_GTK_PATH`` (``os.pathsep``-separated) to add custom
    directories on any OS. Custom dirs take precedence over fallbacks.
    """
    custom = _env_dirs()
    fallbacks = [Path(p) for p in _PLATFORM_FALLBACKS.get(sys.platform, ())]
    candidates = [p for p in (*custom, *fallbacks) if p.is_dir()]

    if sys.platform == "win32":
        _register_windows_dll_dirs(candidates)
    elif sys.platform == "darwin":
        if ctypes.util.find_library(_PROBE_LIB) is None:
            _preload_dylibs(candidates)
    # Linux: rely on system loader / ldconfig.


def ensure_pandoc() -> None:
    """Ensure a pandoc binary is available, downloading via pypandoc if needed."""
    import pypandoc

    try:
        pypandoc.get_pandoc_path()
    except OSError:
        pypandoc.download_pandoc()


def _env_dirs() -> list[Path]:
    raw = os.environ.get(GTK_PATH_ENV, "")
    return [Path(p) for p in raw.split(os.pathsep) if p]


def _register_windows_dll_dirs(candidates: list[Path]) -> None:
    if not hasattr(os, "add_dll_directory"):
        return
    for path in candidates:
        with contextlib.suppress(OSError):
            os.add_dll_directory(str(path))


def _preload_dylibs(candidates: list[Path]) -> None:
    for name in _DARWIN_PRELOAD_ORDER:
        for directory in candidates:
            matches = sorted(directory.glob(f"lib{name}*.dylib"))
            if not matches:
                continue
            with contextlib.suppress(OSError):
                ctypes.CDLL(str(matches[0]), mode=ctypes.RTLD_GLOBAL)
            break
