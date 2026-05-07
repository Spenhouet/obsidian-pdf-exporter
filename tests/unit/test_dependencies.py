"""Tests for native-dep diagnosis."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obsidian_pdf_exporter import dependencies

if TYPE_CHECKING:
    from pathlib import Path


_TSCHOONJ_DLLS = (
    "libgobject-2.0-0.dll",
    "libpango-1.0-0.dll",
    "libpangoft2-1.0-0.dll",
    "libharfbuzz-0.dll",
    "libfontconfig-1.dll",
)


@pytest.fixture
def fake_gtk_dir(tmp_path: Path) -> Path:
    """Directory mimicking a tschoonj GTK3-Runtime-Win64 ``bin`` install."""
    gtk = tmp_path / "GTK3-Runtime Win64" / "bin"
    gtk.mkdir(parents=True)
    for name in _TSCHOONJ_DLLS:
        (gtk / name).write_bytes(b"")
    return gtk


def test_windows_lib_present_matches_mingw_naming(
    monkeypatch: pytest.MonkeyPatch, fake_gtk_dir: Path
) -> None:
    """Detection accepts ``lib<name>-<so>.dll`` from the tschoonj package."""
    monkeypatch.setattr(dependencies.sys, "platform", "win32")
    monkeypatch.setattr(dependencies, "candidate_native_dirs", lambda: [fake_gtk_dir])
    for lib in (
        "gobject-2.0",
        "pango-1.0",
        "pangoft2-1.0",
        "harfbuzz",
        "fontconfig",
    ):
        assert dependencies._lib_present(lib), lib


def test_windows_harfbuzz_subset_accepts_bundled_libharfbuzz(
    monkeypatch: pytest.MonkeyPatch, fake_gtk_dir: Path
) -> None:
    """Bundled libharfbuzz-0.dll counts: tschoonj ships no separate subset DLL."""
    monkeypatch.setattr(dependencies.sys, "platform", "win32")
    monkeypatch.setattr(dependencies, "candidate_native_dirs", lambda: [fake_gtk_dir])
    assert dependencies._lib_present("harfbuzz-subset")


def test_windows_lib_absent_when_dir_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Empty candidate dirs report every lib as missing."""
    monkeypatch.setattr(dependencies.sys, "platform", "win32")
    monkeypatch.setattr(dependencies, "candidate_native_dirs", lambda: [tmp_path])
    for lib in dependencies._REQUIRED_LIBS:
        assert not dependencies._lib_present(lib), lib
