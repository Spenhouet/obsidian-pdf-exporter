---
title: Usage
description: The ope redline command and every flag, commit refs, default output names, recipes for releases, branches and folders, and GitHub Actions workflows for pull requests and releases.
---

# Usage

```text
ope redline ROOT --from-commit REF [--to-commit REF] [OPTIONS]
```

`ROOT` is the folder to compare, the same folder `ope export` takes. The command must run inside the git repository that holds `ROOT`, and both commits must be in its history.

```bash
cd MyVault                      # anywhere inside the repository
ope redline ./Handbook --from-commit v1.0.0
```

## Flags

| Flag | Default | Meaning |
| ---- | ------- | ------- |
| `--from-commit REF` | required | The older version, the baseline. |
| `--to-commit REF` | `HEAD` | The newer version. |
| `-o PATH`, `--output PATH` | `./.export/<title>_redline.pdf` | Where the PDF goes. `.export/` is made in the current folder. |
| `-t TEXT`, `--title TEXT` | the folder name | Title on the first page and in the header. |
| `--subtitle TEXT` | `Changes from <from> to <to>` | Replaces the subtitle. The version label in the footer keeps the hashes. |
| `-T NAME\|PATH`, `--template NAME\|PATH` | `redline` | Another template, see [Styling the redline](styling.md). |
| `-O redline.style=STYLE` | `blackline` | `blackline` or `side-by-side`, see [Styles and options](styles.md). |
| `-O redline.collapse=on` | off | Show only the changes and the headings of their sections. |
| `-O KEY=VALUE`, `--option KEY=VALUE` | | Other options for steps, plugins and the template, as for `export`. |
| `--blame` | off | A strip next to every page with the author, date and commit message of each changed block, see [Blame](blame.md). |
| `--disable-plugin NAME` | | Skip a plugin in both versions. |
| `--toc/--no-toc` | `--toc` | Table of contents at the start. |
| `--debug` | off | Keep the build folder `_build_<name>/` next to the PDF, with `redline_assembled.md` (the diffed Markdown) and `redline_final.html`. |

`export` flags that have no meaning for a redline, such as `--version`, `--date`, `--include` and `--exclude`, are not available. The date in the footer is the day of the export. The full list is in the [CLI reference](../reference/cli.md#redline).

## Which versions

`--from-commit` and `--to-commit` take tags, branches, commit hashes and relative refs such as `HEAD~3`. Both sides are read from git, so uncommitted changes are not included. When `ROOT` does not exist in one of the two commits, that side counts as empty: a folder that is new since `--from-commit` comes out as one big insertion. [Comparing versions](compare.md) has the details: releases, pull requests, the history of one note, and what to do without git.

## Output name and title block

Without `-o`, the PDF is `./.export/<title>_redline.pdf`, for example `.export/Handbook_redline.pdf`. With `--title "Team handbook"` it is `.export/Team handbook_redline.pdf`. With `.` as `ROOT` the title is the name of the current folder.

The title block names the two versions as they were given, and the footer has the short hashes and the date:

```text
Handbook
Changes from v1.0.0 to HEAD
```

`--subtitle "Changes since release 1.0"` replaces the second line. The change summary below the title lists both commits with their hashes, dates and authors, and the commits in between.

## One document or a whole folder

`ROOT` decides what is compared. A folder with subfolders gives one redline of the whole document, with all sections and one table of contents. A section folder gives a redline of that section alone.

```bash
ope redline ./Handbook --from-commit v1.0.0                  # the whole handbook
ope redline ./Handbook/Security --from-commit v1.0.0         # one section
```

A redline for each top-level folder:

```bash
for folder in Policies/*/; do
  ope redline "$folder" --from-commit v1.0.0 -o "out/$(basename "$folder") redline.pdf"
done
```

## In CI

The checkout needs the history of both commits, so set `fetch-depth: 0`. Install ope and its native libraries the same way as for [exports in CI](../getting-started/installation.md#in-ci).

### A redline for every pull request

This workflow builds the redline of a pull request against the point where it left the base branch, uploads it as an artifact and links it in a comment on the pull request:

```yaml title=".github/workflows/redline-pr.yml"
--8<-- "examples/_redline/_ci/redline-pr.yml"
```

The token of a pull request from a fork cannot write comments. For those, keep the upload step and drop the comment step.

### A redline attached to every release

This workflow runs when a release is published. It compares the tag of the release with the tag before it and attaches the PDF to the release:

```yaml title=".github/workflows/redline-release.yml"
--8<-- "examples/_redline/_ci/redline-release.yml"
```
