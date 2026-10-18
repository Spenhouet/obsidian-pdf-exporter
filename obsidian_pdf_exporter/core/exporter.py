"""High-level orchestration: tree → markdown → HTML → PDF."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from obsidian_pdf_exporter.compat.svg_text import apply_svg_text_fix
from obsidian_pdf_exporter.compat.weasyprint_patches import apply_weasyprint_patches
from obsidian_pdf_exporter.core import missing_glyphs
from obsidian_pdf_exporter.core.assemble import assemble_document
from obsidian_pdf_exporter.core.blame import build_index
from obsidian_pdf_exporter.core.blame import range_commits
from obsidian_pdf_exporter.core.blame import write_blame_pdf
from obsidian_pdf_exporter.core.diagram_fit import FitSettings
from obsidian_pdf_exporter.core.html_postprocess import mark_long_words
from obsidian_pdf_exporter.core.html_postprocess import mark_rtl_blocks
from obsidian_pdf_exporter.core.html_postprocess import unlink_missing_targets
from obsidian_pdf_exporter.core.html_postprocess import without_image_data
from obsidian_pdf_exporter.core.image_placeholders import ImagePlaceholders
from obsidian_pdf_exporter.core.mermaid import mermaid_settings
from obsidian_pdf_exporter.core.outside_links import OutsideLinkCounter
from obsidian_pdf_exporter.core.outside_links import outside_mode
from obsidian_pdf_exporter.core.pandoc import render_html
from obsidian_pdf_exporter.core.pdf import apply_decorations
from obsidian_pdf_exporter.core.pdf import html_to_pdf
from obsidian_pdf_exporter.core.pipeline import markdown_dialect
from obsidian_pdf_exporter.core.pipeline import run_document
from obsidian_pdf_exporter.core.pipeline import run_html
from obsidian_pdf_exporter.core.redline import diff_markdown
from obsidian_pdf_exporter.core.redline import extract_commit
from obsidian_pdf_exporter.core.redline import redline_path_info
from obsidian_pdf_exporter.core.redline import redline_source_info
from obsidian_pdf_exporter.core.redline import resolve_short_hash
from obsidian_pdf_exporter.core.redline_html import parse_style
from obsidian_pdf_exporter.core.redline_html import render_redline
from obsidian_pdf_exporter.core.steps import core_steps
from obsidian_pdf_exporter.core.steps.base import DocumentContext
from obsidian_pdf_exporter.core.tree import PageNode
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

if TYPE_CHECKING:
    from collections.abc import Callable


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
    toc: bool = True
    blame: bool = False


@dataclass
class RedlineRequest:
    """All inputs required to build a redline PDF.

    The older version is either a git commit (``from_commit``, with ``to_commit`` as
    the newer one) or a folder or note on disk (``from_path``, compared with ``root``
    as it is on disk).
    """

    root: Path
    output: Path
    template: Template
    from_commit: str = ""
    to_commit: str = "HEAD"
    from_path: Path | None = None
    title: str = ""
    subtitle: str = ""
    options: dict[str, str] = field(default_factory=dict)
    disabled_plugins: set[str] = field(default_factory=set)
    debug: bool = False
    toc: bool = True
    blame: bool = False


@dataclass
class _Sides:
    """The two assembled versions of a redline and how to name them."""

    old_md: str
    new_md: str
    label: str
    subtitle: str
    info: dict[str, str]
    blame_folder: Path | None = None


def export_pdf(  # noqa: PLR0915 - linear pipeline reads better than splitting
    request: ExportRequest,
    *,
    log=print,  # noqa: ANN001 - log is any callable(str)
) -> Path:
    """Build a single PDF from an Obsidian tree according to ``request``."""
    outside_mode(request.options)
    apply_weasyprint_patches(request.options)
    apply_svg_text_fix()
    register_native_dependencies()
    ensure_pandoc()
    log = OutsideLinkCounter(log)

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
        steps = core_steps()

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
            log=log,
            steps=steps,
        )
        label = request.version or git_short_hash(root_folder)
        markdown = _prepend_metadata(markdown, title, request.subtitle, label, date)

        ctx = ExportContext(
            title=title,
            subtitle=request.subtitle,
            version=request.version,
            date=date,
            label=label,
            output_path=output_path,
            build_dir=build_dir,
            options=dict(request.options),
        )
        doc_ctx = DocumentContext(
            build_dir=build_dir,
            options=dict(request.options),
            root=root_folder,
            export=ctx,
            template=request.template,
            plugins=plugins,
            log=log,
        )

        markdown = run_document(markdown, doc_ctx, steps)
        markdown = request.template.process_markdown(markdown, ctx)
        (build_dir / "assembled.md").write_text(markdown, encoding="utf-8")

        log("  Converting to HTML...")
        css_filename = _write_template_assets(request.template, build_dir)

        extra_meta = {}
        if request.version:
            extra_meta["pagetitle"] = f"{title} v{request.version}"

        with ImagePlaceholders(build_dir) as images:
            html = render_html(
                markdown,
                css_filename,
                title,
                build_dir,
                dialect=markdown_dialect(doc_ctx, steps),
                extra_metadata=extra_meta,
                toc=request.toc,
                resource_path=images.folder,
            )
        html = without_image_data(html, partial(run_html, context=doc_ctx, steps=steps))
        html = request.template.process_html(html, ctx)
        html = apply_decorations(html, request.template.decorations(ctx))
        html = unlink_missing_targets(html, lambda m: log(f"  Warning: {m}"))
        html = mark_long_words(mark_rtl_blocks(html))

        (build_dir / "final.html").write_text(images.with_data(html), encoding="utf-8")
        html = images.with_files(html)
        log.summary()

        log("  Generating PDF...")
        fit = _fit_settings(request.options)
        with missing_glyphs.reported(log):
            if request.blame:
                _write_with_blame(html, output_path, build_dir, root_folder, "", log, fit=fit)
            else:
                html_to_pdf(html, output_path, base_url=build_dir.as_uri(), fit=fit)

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
    """Build a redline (tracked-changes) PDF between two versions of a folder or note."""
    outside_mode(request.options)
    apply_weasyprint_patches(request.options)
    apply_svg_text_fix()
    register_native_dependencies()
    ensure_pandoc()
    log = OutsideLinkCounter(log)

    root_folder = _resolve_root(request.root)
    parse_style(request.options)
    if request.from_path is not None and request.blame:
        msg = (
            "--blame needs the git history of both versions; it cannot be used with "
            "--from-path. Use --from-commit, or `ope export --blame` for one version."
        )
        raise ValueError(msg)
    if request.from_path is None and not request.from_commit:
        msg = "redline needs the older version: --from-commit REF or --from-path PATH"
        raise ValueError(msg)
    output_path = request.output.resolve()
    title = request.title or _root_name(root_folder)
    date = today_iso()

    log(f"Building Redline PDF: {title}")
    log(f"  Output: {output_path}")

    build_dir = output_path.parent / f"_build_{output_path.stem}"
    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        plugins = active_plugins(disabled=request.disabled_plugins)
        if plugins:
            log(f"  Active Obsidian plugins: {', '.join(p.name for p in plugins)}")
        steps = core_steps()

        with (
            tempfile.TemporaryDirectory() as tmp_old_str,
            tempfile.TemporaryDirectory() as tmp_new_str,
        ):
            assemble = partial(
                _assemble_if_present,
                build_dir=build_dir,
                log=log,
                plugins=plugins,
                plugin_options=request.options,
            )
            if request.from_path is not None:
                sides = _path_sides(request, root_folder, partial(assemble, new_steps=steps), log)
            else:
                temp = (Path(tmp_old_str), Path(tmp_new_str))
                sides = _commit_sides(
                    request, root_folder, temp, partial(assemble, new_steps=steps), log
                )

            log("  Computing redline diff...")
            diff_body = diff_markdown(sides.old_md, sides.new_md)

            subtitle = request.subtitle or sides.subtitle
            markdown = _prepend_metadata(diff_body, title, subtitle, "", date)
            options = dict(request.options)
            options.update(sides.info)

            ctx = ExportContext(
                title=title,
                subtitle=subtitle,
                date=date,
                label=sides.label,
                output_path=output_path,
                build_dir=build_dir,
                options=options,
            )
            doc_ctx = DocumentContext(
                build_dir=build_dir,
                options=dict(request.options),
                root=root_folder,
                export=ctx,
                template=request.template,
                plugins=plugins,
                redline=True,
                log=log,
            )

            markdown = run_document(markdown, doc_ctx, steps)
            markdown = request.template.process_markdown(markdown, ctx)
            (build_dir / "redline_assembled.md").write_text(markdown, encoding="utf-8")

            log("  Converting to HTML...")
            css_filename = _write_template_assets(request.template, build_dir)

            with ImagePlaceholders(build_dir) as images:
                html = render_html(
                    markdown,
                    css_filename,
                    title,
                    build_dir,
                    dialect=markdown_dialect(doc_ctx, steps),
                    toc=request.toc,
                    resource_path=images.folder,
                )
            html = without_image_data(html, partial(run_html, context=doc_ctx, steps=steps))
            html = render_redline(html, options)
            html = request.template.process_html(html, ctx)
            html = apply_decorations(html, request.template.decorations(ctx))
            html = unlink_missing_targets(html, lambda m: log(f"  Warning: {m}"))
            html = mark_long_words(mark_rtl_blocks(html))

            (build_dir / "redline_final.html").write_text(images.with_data(html), encoding="utf-8")
            html = images.with_files(html)
            log.summary()

            log("  Generating PDF...")
            fit = _fit_settings(request.options)
            with missing_glyphs.reported(log):
                if request.blame and sides.blame_folder is not None:
                    repo = git_root(Path.cwd())
                    _write_with_blame(
                        html,
                        output_path,
                        build_dir,
                        sides.blame_folder,
                        request.to_commit,
                        log,
                        highlight=range_commits(repo, request.from_commit, request.to_commit),
                        range_label=f"{request.from_commit} \u2192 {request.to_commit}",
                        fit=fit,
                    )
                else:
                    html_to_pdf(html, output_path, base_url=build_dir.as_uri(), fit=fit)

            size_kb = output_path.stat().st_size / 1024
            log(f"\n  Redline PDF created: {output_path}")
            log(f"  Size: {size_kb:.1f} KB")
            return output_path
    finally:
        _cleanup(build_dir, output_path, debug=request.debug, log=log)


def _commit_sides(
    request: RedlineRequest,
    root_folder: Path,
    temp: tuple[Path, Path],
    assemble: Callable[..., str],
    log: Callable[[str], object],
) -> _Sides:
    """Assemble ``root_folder`` as it is in ``from_commit`` and in ``to_commit``."""
    if not is_git_repo(Path.cwd()):
        msg = (
            "redline requires the vault to be in a git repository. "
            "Run `git init` and commit your vault, use --from-path to compare two folders "
            "or notes, or use `export` instead."
        )
        raise RuntimeError(msg)
    repo = git_root(Path.cwd())
    tmp_old, tmp_new = temp
    try:
        rel_path = root_folder.relative_to(repo)
    except ValueError as e:
        msg = f"root {root_folder} is not inside repo root {repo}"
        raise ValueError(msg) from e
    from_hash = resolve_short_hash(request.from_commit, repo)
    to_hash = resolve_short_hash(request.to_commit, repo)
    log(f"  From: {from_hash}  ->  To: {to_hash}")

    log("  Extracting old commit...")
    extract_commit(request.from_commit, tmp_old, repo)
    log("  Extracting new commit...")
    extract_commit(request.to_commit, tmp_new, repo)

    old_md = assemble(
        tmp_old / rel_path,
        vault_root=tmp_old,
        missing=f"  Note: path not found in {from_hash}",
    )
    new_md = assemble(
        tmp_new / rel_path,
        vault_root=tmp_new,
        missing=f"  Note: path not found in {to_hash}",
        new=True,
    )
    return _Sides(
        old_md=old_md,
        new_md=new_md,
        label=f"Redline: {from_hash} -> {to_hash}",
        subtitle=f"Changes from {request.from_commit} to {request.to_commit}",
        info=redline_source_info(repo, request.from_commit, request.to_commit, rel_path),
        blame_folder=repo / rel_path,
    )


def _path_sides(
    request: RedlineRequest,
    root_folder: Path,
    assemble: Callable[..., str],
    log: Callable[[str], object],
) -> _Sides:
    """Assemble the folder or note ``from_path`` and ``root_folder`` as they are on disk.

    Each side resolves its links and embeds in its own vault: the closest folder above
    it with ``.obsidian`` (or ``.git``), else the folder itself.
    """
    assert request.from_path is not None  # noqa: S101 - checked by the caller
    old_root = _resolve_root(request.from_path)
    if old_root.is_file() != root_folder.is_file():
        msg = (
            "--from-path and ROOT must both be folders or both be notes: "
            f"{old_root} and {root_folder}"
        )
        raise ValueError(msg)
    log(f"  From: {old_root}  ->  To: {root_folder}")
    sides = []
    for root in (old_root, root_folder):
        start = root.parent if root.is_file() else root
        vault = find_vault_root(start)
        sides.append(assemble(root, vault_root=vault, missing="", new=root is root_folder))
    return _Sides(
        old_md=sides[0],
        new_md=sides[1],
        label=f"Redline: {_root_name(old_root)} -> {_root_name(root_folder)}",
        subtitle=f"Changes from {request.from_path} to {request.root}",
        info=redline_path_info(old_root, root_folder, str(request.from_path), str(request.root)),
    )


def _write_with_blame(
    html: str,
    output_path: Path,
    build_dir: Path,
    folder: Path,
    commit: str,
    log: Callable[[str], object],
    *,
    highlight: set[str] | None = None,
    range_label: str = "",
    fit: FitSettings | None = None,
) -> None:
    """Write the PDF with the blame strip next to every page."""
    start = folder if folder.exists() else Path.cwd()
    if not is_git_repo(start):
        log("  Warning: --blame needs a git repository; the PDF has no blame strip")
        html_to_pdf(html, output_path, base_url=build_dir.as_uri(), fit=fit)
        return
    log("  Reading the git history (blame)...")
    index = build_index(git_root(start), folder, commit)
    share = write_blame_pdf(
        html,
        output_path,
        build_dir.as_uri(),
        index,
        highlight=highlight,
        range_label=range_label,
        fit=fit,
    )
    log(f"  Blame: {share:.0%} of the blocks matched a source line")


def _fit_settings(options: dict[str, str]) -> FitSettings | None:
    """Return how tall Mermaid diagrams are fitted to the page, or None when turned off."""
    settings = mermaid_settings(dict(options))
    if not settings.fit:
        return None
    return FitSettings(min_font_pt=settings.landscape_min_font)


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
    label: str,
    date: str,
) -> str:
    lines = [f"% {title}"]
    if subtitle:
        lines.append(f"% {subtitle}")
    if label and date:
        lines.append(f"% {label} | {date}")
    elif label:
        lines.append(f"% {label}")
    elif date:
        lines.append(f"% {date}")
    return "\n".join(lines) + "\n\n" + body


def _write_template_assets(template: Template, build_dir: Path) -> str:
    css_filename = f"{template.name}.css"
    (build_dir / css_filename).write_text(template.get_css(), encoding="utf-8")
    build_dir_resolved = build_dir.resolve()
    for name, content in template.assets().items():
        dest = (build_dir / name).resolve()
        if dest.is_relative_to(build_dir_resolved):
            dest.write_bytes(content)
    return css_filename


def _assemble_if_present(
    root_dir: Path,
    *,
    build_dir: Path,
    vault_root: Path,
    log,  # noqa: ANN001
    missing: str,
    plugins: list | None = None,
    plugin_options: dict[str, str] | None = None,
    new: bool = False,
    new_steps: list | None = None,
) -> str:
    """Assemble the folder or note ``root_dir``; an empty document when it does not exist.

    The newer side (``new``) runs ``new_steps``, the steps that also run on the diffed
    document; the older side runs a fresh set.
    """
    if not root_dir.exists():
        log(missing + " — treating as empty")
        return ""
    log(f"  Indexing vault at {vault_root}...")
    vault_index = VaultIndex(vault_root)
    log(f"  Building tree at {root_dir.name}...")
    if root_dir.is_file():
        tree = PageNode(folder=root_dir.parent, name=root_dir.stem, md_file=root_dir)
    else:
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
        log=log,
        steps=new_steps if new and new_steps is not None else core_steps(),
    )


def _root_name(root: Path) -> str:
    """The name of a folder, or of a note without ``.md``."""
    return root.stem if root.is_file() else root.name


def _cleanup(build_dir: Path, output_path: Path, *, debug: bool, log) -> None:  # noqa: ANN001
    if not debug and output_path.exists() and build_dir.exists():
        with suppress(OSError):
            shutil.rmtree(build_dir)
    elif debug and build_dir.exists():
        log(f"  Debug: build dir kept at {build_dir}")
