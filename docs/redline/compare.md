---
title: Comparing versions
description: Which two versions a redline compares. Git commits, tags, branches, HEAD~n, the history of one note, a pull request against main, CI, and two folders or notes on disk without git.
---

# Comparing versions

A redline compares two versions of a folder or a note. They come from one of two places:

- Git: `--from-commit` names the older commit and `--to-commit` the newer one (default `HEAD`). The command runs inside the repository, and both commits must be in its history.
- Disk: `--from-path` names an older copy of the folder or note, and `ROOT` is the newer one, both read as they are on disk. No git is needed. See [Without git](#without-git).

The two ways cannot be mixed: `--from-path` is refused together with `--from-commit` or `--to-commit`.

## Git refs

Both flags take anything git resolves to a commit:

| Ref | Example | Compares |
| --- | ------- | -------- |
| Tag | `--from-commit v1.0.0 --to-commit v1.1.0` | Two releases |
| Branch | `--from-commit main` | The tip of `main` with `HEAD` |
| Remote branch | `--from-commit origin/main` | The fetched tip of `main` with `HEAD` |
| Commit hash, full or short | `--from-commit 3f2c9a1` | One commit with `HEAD` |
| Relative ref | `--from-commit HEAD~3`, `--from-commit v1.1.0^` | Three commits back, or the commit before a tag |
| Date | `--from-commit 'main@{2026-01-01}'` | `main` as it was on a date (from the reflog, so only in a clone that has seen it) |

Both sides are read from git, never from the working tree. Uncommitted changes are not part of either version, so commit them first.

A range such as `v1.0.0..v1.1.0` is not accepted: name the two ends with the two flags. An unknown ref stops the command with exit code 1 and the error from git.

## Releases

A release against the previous release:

```bash
ope redline ./Handbook --from-commit v1.0.0 --to-commit v1.1.0
```

The latest tag against the tag before it:

```bash
new=$(git describe --tags --abbrev=0)
old=$(git describe --tags --abbrev=0 "$new^")
ope redline ./Handbook --from-commit "$old" --to-commit "$new" --subtitle "Changes from $old to $new"
```

## A branch or pull request against main

A reviewer wants the changes of the branch alone. Compare against the merge base, the commit where the branch left `main`:

```bash
ope redline ./Handbook --from-commit "$(git merge-base origin/main HEAD)"
```

`--from-commit main` also shows, reversed, every change made on `main` since the branch was created.

## The history of one note or folder

`git log` with a path lists the commits that changed it. Pick two of them:

```bash
git log --format='%h %ad %s' --date=short -- Handbook/Security
ope redline ./Handbook/Security --from-commit 3f2c9a1 --to-commit 8b41d07
```

`ROOT` can also be a single note. Then only that note is compared, as a document of one page:

```bash
ope redline ./Handbook/Security/Security.md --from-commit 3f2c9a1
```

A redline of the parent folder still shows the changes of the whole document, with every section.

The last commit that changed a folder against the one before it:

```bash
last=$(git log -1 --format=%h -- Handbook/Security)
ope redline ./Handbook/Security --from-commit "$last^" --to-commit "$last"
```

## In CI

The checkout must hold the history of both commits: `fetch-depth: 0` in `actions/checkout`. The [Usage](usage.md#in-ci) page has complete GitHub Actions workflows that attach a redline to a pull request (against the merge base) and to a release (against the previous tag).

## Without git

`--from-path` compares two folders, or two notes, as they are on disk. `ROOT` is the newer version and `--from-path` the older one:

```bash
ope redline ./Handbook --from-path ./archive/handbook-1.0/Handbook          # folder against folder
ope redline ./Handbook/Security.md --from-path ./old/Security.md            # note against note
```

Both must be folders, or both must be notes. Neither side has to be in git, and uncommitted changes are included because the files are read from disk. This also compares the working tree with an older copy, or two exports of a vault from different places.

Each side is read in its own vault: links, embeds and images are looked up from the closest folder above it that holds `.obsidian` (or `.git`). Without such a folder, the folder of the side itself is the vault, so notes and images outside of it are not found. Copy the whole vault, or at least its `.obsidian` folder and the attachments, when the folder embeds files from elsewhere. A copy of an old version made with `git archive` keeps the vault together:

```bash
mkdir -p /tmp/handbook-1.0
git archive v1.0.0 | tar -x -C /tmp/handbook-1.0
ope redline ./Handbook --from-path /tmp/handbook-1.0/Handbook
```

The change summary names both paths as they were given, each with the date of the newest file in it (`(folder, modified 2026-03-30)`), and lists no commits. The subtitle is `Changes from <old path> to <new path>` unless `--subtitle` replaces it. `--blame` needs the git history of both versions and is refused with `--from-path`.

Two PDFs cannot be compared: ope reads the Markdown, not the PDF.
