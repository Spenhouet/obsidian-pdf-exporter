"""High-level orchestration: tree → markdown → HTML → PDF."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from obsidian_pdf_exporter.core.assemble import assemble_document
from obsidian_pdf_exporter.core.html_postprocess import inline_svg_images
from obsidian_pdf_exporter.core.html_postprocess import normalize_colgroups
from obsidian_pdf_exporter.core.html_postprocess import remove_empty_table_headers
from obsidian_pdf_exporter.core.html_postprocess import wrap_wide_tables
from obsidian_pdf_exporter.core.pandoc import render_html
from obsidian_pdf_exporter.core.pdf import apply_decorations
from obsidian_pdf_exporter.core.pdf import html_to_pdf
from obsidian_pdf_exporter.core.redline import diff_markdown
from obsidian_pdf_exporter.core.redline import extract_commit
from obsidian_pdf_exporter.core.redline import resolve_short_hash
from obsidian_pdf_exporter.core.tree import build_space_tree
from obsidian_pdf_exporter.core.tree import collect_page_index
from obsidian_pdf_exporter.core.util import git_root
from obsidian_pdf_exporter.core.util import git_short_hash
from obsidian_pdf_exporter.core.util import is_git_repo
from obsidian_pdf_exporter.core.util import today_iso
from obsidian_pdf_exporter.core.util import vault_root as find_vault_root
from obsidian_pdf_exporter.core.vault_index import VaultIndex
from obsidian_pdf_exporter.plugins import active_plugins
from obsidian_pdf_exporter.runtime import ensure_pandoc
from obsidian_pdf_exporter.runtime import register_native_dependencies
from obsidian_pdf_exporter.templates.base import ExportContext
from obsidian_pdf_exporter.templates.base import Template


@dataclass
class ExportRequest:
    """All inputs required to build a single PDF export."""

    root: Path
    output: Path
    template: Template
    title: str = ""
    subtitle: str = ""
    version: str = ""
    date: str = ""
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)
    disabled_plugins: set[str] = field(default_factory=set)
    debug: bool = False


@dataclass
class RedlineRequest:
    """All inputs required to build a redline (between two git commits) PDF."""

    root: Path
    output: Path
    template: Template
    from_commit: str
    to_commit: str = "HEAD"
    title: str = ""
    subtitle: str = ""
    options: dict[str, str] = field(default_factory=dict)
    disabled_plugins: set[str] = field(default_factory=set)
    debug: bool = False


def export_pdf(  # noqa: PLR0915 - linear pipeline reads better than splitting
    request: ExportRequest,
    *,
    log=print,  # noqa: ANN001 - log is any callable(str)
) -> Path:
    """Build a single PDF from an Obsidian tree according to ``request``."""
    register_native_dependencies()
    ensure_pandoc()

    root_folder = _resolve_root(request.root)
    output_path = request.output.resolve()
    title = request.title or root_folder.name
    date = request.date or today_iso()

    log(f"Building PDF: {title}")
    log(f"  Root: {root_folder}")
    log(f"  Template: {request.template.name}")
    log(f"  Output: {output_path}")

    build_dir = output_path.parent / f"_build_{output_path.stem}"
    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        plugins = active_plugins(disabled=request.disabled_plugins)
        if plugins:
            log(f"  Active Obsidian plugins: {', '.join(p.name for p in plugins)}")

        vault_root_path = find_vault_root(root_folder)
        log(f"  Indexing vault at {vault_root_path}...")
        vault_index = VaultIndex(vault_root_path)
        log(f"  Indexed {len(vault_index.md_files())} markdown files")

        log("  Building page tree...")
        tree = build_space_tree(root_folder, plugins=plugins, vault_index=vault_index)
        if tree is None:
            msg = f"No documentation found at {root_folder}"
            raise ValueError(msg)
        if request.include:
            tree.children = [c for c in tree.children if c.name in request.include]
        if request.exclude:
            tree.children = [c for c in tree.children if c.name not in request.exclude]

        log("  Building page index...")
        page_index = collect_page_index(tree)
        log(f"  Indexed {len(page_index)} pages")

        log("  Assembling document...")
        markdown = assemble_document(
            tree,
            page_index,
            build_dir,
            vault_root_path,
            plugins=plugins,
            plugin_options=request.options,
            vault_index=vault_index,
        )
        markdown = _prepend_metadata(markdown, title, request.subtitle, request.version, date)

        ctx = ExportContext(
            title=title,
            subtitle=request.subtitle,
            version=request.version,
            date=date,
            label=request.version or git_short_hash(root_folder),
            output_path=output_path,
            build_dir=build_dir,
            options=dict(request.options),
        )

        markdown = request.template.process_markdown(markdown, ctx)
        (build_dir / "assembled.md").write_text(markdown, encoding="utf-8")

        log("  Converting to HTML...")
        css_filename = _write_template_assets(request.template, build_dir)

        extra_meta = {}
        if request.version:
            extra_meta["pagetitle"] = f"{title} v{request.version}"

        html = render_html(markdown, css_filename, title, build_dir, extra_metadata=extra_meta)
        html = remove_empty_table_headers(html)
        html = normalize_colgroups(html)
        html = inline_svg_images(html, build_dir)
        html, has_wide = wrap_wide_tables(html)
        if has_wide:
            log("  Wide tables detected — landscape orientation applied for those pages")

        html = request.template.process_html(html, ctx)
        html = apply_decorations(html, request.template.decorations(ctx))

        log("  Generating PDF...")
        html_to_pdf(html, output_path, base_url=build_dir.as_uri())

        size_kb = output_path.stat().st_size / 1024
        log(f"\n  PDF created: {output_path}")
        log(f"  Size: {size_kb:.1f} KB")
        return output_path
    finally:
        _cleanup(build_dir, output_path, debug=request.debug, log=log)


def export_redline(  # noqa: PLR0915 - linear pipeline reads better than splitting
    request: RedlineRequest,
    *,
    log=print,  # noqa: ANN001 - log is any callable(str)
) -> Path:
    """Build a redline (tracked-changes) PDF between two git commits."""
    register_native_dependencies()
    ensure_pandoc()

    root_folder = _resolve_root(request.root)
    if not is_git_repo(Path.cwd()):
        msg = (
            "redline requires the vault to be in a git repository. "
            "Run `git init` and commit your vault, or use `export` instead."
        )
        raise RuntimeError(msg)
    repo = git_root(Path.cwd())
    output_path = request.output.resolve()

    from_hash = resolve_short_hash(request.from_commit, repo)
    to_hash = resolve_short_hash(request.to_commit, repo)
    title = request.title or root_folder.name
    date = today_iso()

    log(f"Building Redline PDF: {title}")
    log(f"  From: {from_hash}  ->  To: {to_hash}")
    log(f"  Output: {output_path}")

    build_dir = output_path.parent / f"_build_{output_path.stem}"
    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        try:
            rel_path = root_folder.relative_to(repo)
        except ValueError as e:
            msg = f"root {root_folder} is not inside repo root {repo}"
            raise ValueError(msg) from e

        with (
            tempfile.TemporaryDirectory() as tmp_old_str,
            tempfile.TemporaryDirectory() as tmp_new_str,
        ):
            tmp_old = Path(tmp_old_str)
            tmp_new = Path(tmp_new_str)

            log("  Extracting old commit...")
            extract_commit(request.from_commit, tmp_old, repo)
            log("  Extracting new commit...")
            extract_commit(request.to_commit, tmp_new, repo)

            old_root = tmp_old / rel_path
            new_root = tmp_new / rel_path

            plugins = active_plugins(disabled=request.disabled_plugins)
            if plugins:
                log(f"  Active Obsidian plugins: {', '.join(p.name for p in plugins)}")

            old_md = _assemble_if_present(
                old_root,
                build_dir,
                tmp_old,
                log,
                missing=f"  Note: path not found in {from_hash}",
                plugins=plugins,
                plugin_options=request.options,
            )
            new_md = _assemble_if_present(
                new_root,
                build_dir,
                tmp_new,
                log,
                missing=f"  Note: path not found in {to_hash}",
                plugins=plugins,
                plugin_options=request.options,
            )

            log("  Computing redline diff...")
            diff_body = diff_markdown(old_md, new_md)

            label = f"Redline: {from_hash} -> {to_hash}"
            markdown = _prepend_metadata(diff_body, title, request.subtitle or label, "", date)

            ctx = ExportContext(
                title=title,
                subtitle=request.subtitle or label,
                date=date,
                label=label,
                output_path=output_path,
                build_dir=build_dir,
                options=dict(request.options),
            )

            markdown = request.template.process_markdown(markdown, ctx)
            (build_dir / "redline_assembled.md").write_text(markdown, encoding="utf-8")

            log("  Converting to HTML...")
            css_filename = _write_template_assets(request.template, build_dir)

            html = render_html(markdown, css_filename, title, build_dir)
            html = remove_empty_table_headers(html)
            html = normalize_colgroups(html)
            html = inline_svg_images(html, build_dir)
            html = request.template.process_html(html, ctx)
            html = apply_decorations(html, request.template.decorations(ctx))

            log("  Generating PDF...")
            html_to_pdf(html, output_path, base_url=build_dir.as_uri())

            size_kb = output_path.stat().st_size / 1024
            log(f"\n  Redline PDF created: {output_path}")
            log(f"  Size: {size_kb:.1f} KB")
            return output_path
    finally:
        _cleanup(build_dir, output_path, debug=request.debug, log=log)


def _resolve_root(root: Path) -> Path:
    folder = root.resolve()
    if not folder.exists() and folder.parent.name == folder.name and folder.parent.is_dir():
        folder = folder.parent
    if not folder.exists():
        msg = f"Root path not found: {folder}"
        raise FileNotFoundError(msg)
    return folder


def _prepend_metadata(
    body: str,
    title: str,
    subtitle: str,
    version: str,
    date: str,
) -> str:
    lines = [f"% {title}"]
    if subtitle:
        lines.append(f"% {subtitle}")
    if version:
        lines.append(f"% Version {version} | {date}")
    elif date:
        lines.append(f"% {date}")
    return "\n".join(lines) + "\n\n" + body


def _write_template_assets(template: Template, build_dir: Path) -> str:
    css_filename = f"{template.name}.css"
    (build_dir / css_filename).write_text(template.get_css(), encoding="utf-8")
    for name, content in template.assets().items():
        (build_dir / name).write_bytes(content)
    return css_filename


def _assemble_if_present(
    root_dir: Path,
    build_dir: Path,
    vault_root: Path,
    log,  # noqa: ANN001
    missing: str,
    *,
    plugins: list | None = None,
    plugin_options: dict[str, str] | None = None,
) -> str:
    if not root_dir.exists():
        log(missing + " — treating as empty")
        return ""
    log(f"  Indexing vault at {vault_root}...")
    vault_index = VaultIndex(vault_root)
    log(f"  Building tree at {root_dir.name}...")
    tree = build_space_tree(root_dir, plugins=plugins, vault_index=vault_index)
    if tree is None:
        return ""
    idx = collect_page_index(tree)
    return assemble_document(
        tree,
        idx,
        build_dir,
        vault_root,
        plugins=plugins,
        plugin_options=plugin_options,
        vault_index=vault_index,
    )


def _cleanup(build_dir: Path, output_path: Path, *, debug: bool, log) -> None:  # noqa: ANN001
    if not debug and output_path.exists() and build_dir.exists():
        with suppress(OSError):
            shutil.rmtree(build_dir)
    elif debug and build_dir.exists():
        log(f"  Debug: build dir kept at {build_dir}")
