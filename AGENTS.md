# AGENTS.md

Guidance for coding agents that work on obsidian-pdf-exporter (`ope`). Users of the CLI find the docs at https://spenhouet.com/obsidian-pdf-exporter/ and an agent skill in `skills/obsidian-pdf-exporter/`.

## Setup and checks

```bash
uv sync --all-groups
uv run ruff check   # lint, must pass
uv run pytest       # tests, must pass
uv run ope --help
```

Python 3.10+, managed with uv. Line length 100, Google docstrings, one import per line, absolute imports only. Do not silence ruff findings with `noqa` unless the rule truly does not apply.

## Architecture

An export reads a folder of notes and writes one PDF in three layers:

1. Markdown dialect: `obsidian_pdf_exporter/core/dialect.py`, the pandoc reader extensions and arguments.
2. Obsidian core syntax: one step per feature in `obsidian_pdf_exporter/core/steps/`, listed in `CORE_STEPS` in `core/steps/__init__.py`. The order matters and is explained in that module's docstring.
3. Community plugins: `obsidian_pdf_exporter/plugins/<name>/`, registered as entry points in `pyproject.toml`, run inside the `plugins` step.

Templates (`obsidian_pdf_exporter/templates/`) only change the look: CSS, header and footer, page rules.

Files that go into the build folder (images, rendered drawings, PDF pages) are named by their content (`core/build_files.py`), so a redline sees a file that was replaced under the same name.

Pandoc embeds a short placeholder instead of each raster image of the build folder (`core/image_placeholders.py`). The steps see the small HTML; `final.html` gets the image data back, and WeasyPrint gets `file:` URLs of the images.

`ope redline` diffs the assembled Markdown of two commits, or of two folders or notes with `--from-path` (`core/redline.py`), then lays the HTML out in the chosen style with the change summary (`core/redline_html.py`, `redline_side_by_side.py`, `redline_collapse.py`). `--blame` (`core/blame.py`) renders the PDF unchanged and adds a strip next to every page. The CSS of the change marks is in `core/assets/` and comes before the template CSS.

Where new code goes:

- Syntax Obsidian supports without plugins: a new step, see CONTRIBUTING.md "Adding a core syntax step".
- Syntax of a community plugin: a plugin package, see CONTRIBUTING.md "Adding support for an Obsidian plugin".
- Layout and styling: the template CSS, not a step.

Rules:

- Leave code as written: wrap rewrites in `outside_code` from `core/code.py`.
- Never drop content silently. Keep what cannot be rendered in a simple form and call `context.warn(...)`.
- New steps or plugins need tests in `tests/unit/`; `test_steps.py` checks the step order.

## Docs

The docs site is `mkdocs.yml` plus `docs/`, built with Zensical and deployed by `.github/workflows/docs.yml`.

```bash
uv run zensical build --strict              # must pass
uv run python scripts/gen_cli_docs.py       # after changing a command or flag
uv run python scripts/render_examples.py    # after a change to the rendered output
uv run python scripts/render_redline_examples.py  # after a change to redline output
uv run python scripts/render_home.py          # after the two above, for the home page
uv run python scripts/gen_llms_txt.py       # after adding or renaming a page
```

- A feature needs an example note in `examples/<name>/<name>.md`, a screenshot from `render_examples.py` (commit `docs/img/features/<name>.png`), and a section on the docs page of its layer with the `ope-example` block (source included with `--8<--`).
- Do not edit `docs/reference/cli.md`, `docs/llms.txt` or `docs/llms-full.txt` by hand; CI checks they are current.
- Docs use a neutral voice and plain words. No company or customer names in examples.

## Pull requests

Small and focused. Run ruff, pytest and the strict docs build before pushing. Reference the issue (`Closes #n`). Follow `.github/PULL_REQUEST_TEMPLATE.md`.
