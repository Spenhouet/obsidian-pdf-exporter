"""Template registry / discovery / filesystem-template tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from obsidian_pdf_exporter.templates import FilesystemTemplate
from obsidian_pdf_exporter.templates import available_templates
from obsidian_pdf_exporter.templates import load_from_path
from obsidian_pdf_exporter.templates import load_template
from obsidian_pdf_exporter.templates import register_template
from obsidian_pdf_exporter.templates import resolve_template
from obsidian_pdf_exporter.templates import template_sources
from obsidian_pdf_exporter.templates.base import ExportContext
from obsidian_pdf_exporter.templates.base import Template


def test_builtin_templates_discoverable() -> None:
    names = available_templates()
    assert "default" in names
    assert "redline" in names


def test_template_sources_marks_builtins() -> None:
    sources = template_sources()
    assert sources["default"] == "builtin"
    assert sources["redline"] == "builtin"


def test_load_template_returns_instance() -> None:
    tpl = load_template("default")
    assert isinstance(tpl, Template)
    assert tpl.name == "default"
    css = tpl.get_css()
    assert "@page" in css


def test_runtime_register_template_round_trip() -> None:
    class _Mock(Template):
        name = "mock-template-test"

        def get_css(self) -> str:
            return "body {}"

    register_template(_Mock)
    tpl = load_template("mock-template-test")
    assert isinstance(tpl, _Mock)
    assert tpl.get_css() == "body {}"


def test_register_instance_directly() -> None:
    instance = FilesystemTemplate(
        name="inst-template-test",
        description="",
        css="body {}",
        assets={},
        running_html="",
        page_css="",
        source_path=Path(),
    )
    register_template(instance)
    loaded = load_template("inst-template-test")
    assert loaded is instance


def test_load_from_single_css_file(tmp_path: Path) -> None:
    css = tmp_path / "brand.css"
    css.write_text("body { color: red; }", encoding="utf-8")

    tpl = load_from_path(css)
    assert tpl.name == "brand"
    assert tpl.get_css() == "body { color: red; }"
    assert tpl.assets() == {}
    assert tpl.decorations(_ctx()) is None


def test_load_directory_with_manifest(tmp_path: Path) -> None:
    (tmp_path / "main.css").write_text("body{}", encoding="utf-8")
    (tmp_path / "header.html").write_text("<div id='h'>X</div>", encoding="utf-8")
    (tmp_path / "page.css").write_text("@page { margin: 2cm; }", encoding="utf-8")
    (tmp_path / "logo.svg").write_bytes(b"<svg/>")
    (tmp_path / "template.yaml").write_text(
        "name: legal\n"
        "description: Legal cover\n"
        "css: main.css\n"
        "assets: [logo.svg]\n"
        "running_html: header.html\n"
        "page_css: page.css\n",
        encoding="utf-8",
    )

    tpl = load_from_path(tmp_path)
    assert tpl.name == "legal"
    assert tpl.description == "Legal cover"
    assert tpl.get_css() == "body{}"
    assert tpl.assets() == {"logo.svg": b"<svg/>"}
    decs = tpl.decorations(_ctx())
    assert decs is not None
    assert "id='h'" in decs.running_html
    assert "@page" in decs.page_css


def test_running_html_inlines_declared_assets(tmp_path: Path) -> None:
    (tmp_path / "main.css").write_text("body{}", encoding="utf-8")
    (tmp_path / "header.html").write_text(
        '<div><img src="logo.svg" alt="L"><img src="https://x/y.png"></div>',
        encoding="utf-8",
    )
    (tmp_path / "logo.svg").write_bytes(b"<svg/>")
    (tmp_path / "template.yaml").write_text(
        "css: main.css\nassets: [logo.svg]\nrunning_html: header.html\n",
        encoding="utf-8",
    )

    tpl = load_from_path(tmp_path)
    decs = tpl.decorations(_ctx())
    assert decs is not None
    assert 'src="logo.svg"' not in decs.running_html
    assert "data:image/svg+xml;base64,PHN2Zy8+" in decs.running_html
    # Non-asset external URL must pass through untouched.
    assert 'src="https://x/y.png"' in decs.running_html


def test_page_css_inlines_url_refs(tmp_path: Path) -> None:
    (tmp_path / "main.css").write_text("body{}", encoding="utf-8")
    (tmp_path / "page.css").write_text(
        "@page { background: url(logo.svg); }",
        encoding="utf-8",
    )
    (tmp_path / "logo.svg").write_bytes(b"<svg/>")
    (tmp_path / "template.yaml").write_text(
        "css: main.css\nassets: [logo.svg]\npage_css: page.css\n",
        encoding="utf-8",
    )

    tpl = load_from_path(tmp_path)
    decs = tpl.decorations(_ctx())
    assert decs is not None
    assert "url(logo.svg)" not in decs.page_css
    assert "data:image/svg+xml;base64,PHN2Zy8+" in decs.page_css


def test_load_directory_without_manifest_auto_discovers(tmp_path: Path) -> None:
    (tmp_path / "template.css").write_text("body{}", encoding="utf-8")
    (tmp_path / "logo.svg").write_bytes(b"<svg/>")
    (tmp_path / "footer.png").write_bytes(b"PNG")

    tpl = load_from_path(tmp_path)
    assert tpl.name == tmp_path.name
    assert tpl.get_css() == "body{}"
    assert tpl.assets() == {"footer.png": b"PNG", "logo.svg": b"<svg/>"}
    assert tpl.decorations(_ctx()) is None


def test_load_directory_single_css_disambiguation(tmp_path: Path) -> None:
    (tmp_path / "only.css").write_text("body{}", encoding="utf-8")
    tpl = load_from_path(tmp_path)
    assert tpl.get_css() == "body{}"


def test_load_directory_multiple_css_without_manifest_errors(tmp_path: Path) -> None:
    (tmp_path / "a.css").write_text("", encoding="utf-8")
    (tmp_path / "b.css").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Multiple CSS files"):
        load_from_path(tmp_path)


def test_load_missing_path_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_from_path(tmp_path / "nope")


def test_load_manifest_missing_asset_errors(tmp_path: Path) -> None:
    (tmp_path / "template.css").write_text("body{}", encoding="utf-8")
    (tmp_path / "template.yaml").write_text("assets: [missing.svg]\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"missing\.svg"):
        load_from_path(tmp_path)


def test_resolve_template_prefers_path(tmp_path: Path) -> None:
    css = tmp_path / "default.css"
    css.write_text("/* override */", encoding="utf-8")

    tpl = resolve_template(str(css))
    assert tpl.get_css() == "/* override */"


def test_resolve_template_falls_back_to_registry() -> None:
    tpl = resolve_template("default")
    assert tpl.name == "default"


def test_user_config_dir_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user_dir = tmp_path / "templates"
    brand = user_dir / "user-brand-test"
    brand.mkdir(parents=True)
    (brand / "template.css").write_text("body{}", encoding="utf-8")

    monkeypatch.setenv("OBSIDIAN_PDF_EXPORTER_TEMPLATES_DIR", str(user_dir))

    sources = template_sources()
    assert "user-brand-test" in sources
    assert sources["user-brand-test"].startswith("user-config")
    tpl = load_template("user-brand-test")
    assert tpl.get_css() == "body{}"


def _ctx() -> ExportContext:
    return ExportContext(title="t")
