---
title: Comparing versions
description: Which two versions a redline compares. Git commits, tags, branches, HEAD~n, the history of one note, a pull request against main, CI, and what to do when the versions are not in git.
---

# Comparing versions

A redline compares two versions of a folder. Today both versions come from git: `--from-commit` names the older one and `--to-commit` the newer one (default `HEAD`). The command runs inside the repository, and both commits must be in its history.

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

`ROOT` is always a folder. To redline one note, give it its own folder named like the note (`Security/Security.md`), as for [`ope export`](../obsidian/structure.md). A redline of the parent folder still shows the changes of the whole document, with every section.

The last commit that changed a folder against the one before it:

```bash
last=$(git log -1 --format=%h -- Handbook/Security)
ope redline ./Handbook/Security --from-commit "$last^" --to-commit "$last"
```

## In CI

The checkout must hold the history of both commits: `fetch-depth: 0` in `actions/checkout`. The [Usage](usage.md#in-ci) page has complete GitHub Actions workflows that attach a redline to a pull request (against the merge base) and to a release (against the previous tag).

## Without git

ope can only compare git commits today. Comparing two folders, two notes or two exported versions directly, without git, is planned: [#92](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/92).

Until then, two copies of a folder can be put into a throwaway repository, one commit each:

```bash
old=./handbook-1.0/Handbook   # the older copy of the folder
new=./Handbook                # the newer copy
work=$(mktemp -d)
git -C "$work" init -q
cp -r "$old" "$work/Handbook"
git -C "$work" add -A && git -C "$work" -c user.name=redline -c user.email=redline@localhost commit -qm old
rm -rf "$work/Handbook" && cp -r "$new" "$work/Handbook"
git -C "$work" add -A && git -C "$work" -c user.name=redline -c user.email=redline@localhost commit -qm new
out="$PWD/Handbook_redline.pdf"
(cd "$work" && ope redline ./Handbook --from-commit HEAD~1 -o "$out")
rm -rf "$work"
```

Notes, images and attachments outside the folder are not copied, so embeds of them stay unresolved. Copy them into the throwaway repository too when the folder embeds them. The docs screenshots of this section are made the same way, see `scripts/render_redline_examples.py`.

Two PDFs cannot be compared: ope reads the Markdown, not the PDF.
