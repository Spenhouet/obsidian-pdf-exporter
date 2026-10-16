---
title: Redline
description: Tracked-changes PDFs between two git commits of a vault. What a redline is, who it is for, how ope builds it and what the reader sees.
---

# Redline

`ope redline` builds a tracked-changes PDF of a folder between two git commits. Inserted text is green and underlined, removed text is red and struck through, and the rest of the document is exactly as it is in the newer commit. A reader sees every change in context, in the same layout as the released PDF.

```bash
ope redline ./Policy --from-commit v1.0.0 --to-commit v1.1.0
```

![Before, after and redline of a short policy, next to each other](../img/redline/redline-three-up.png)

## Who it is for

A redline answers "what changed since the version I approved?" without a diff tool and without reading Markdown. Typical uses:

- Document control: every new release of a procedure, policy or manual goes out with a redline against the previous release.
- Reviews and approvals: the reviewer of a pull request reads the redline PDF instead of the raw diff.
- Audits: the change history of a controlled document can be shown for any two versions, at any time, from the git history.
- Change requests: the PDF of a proposed change is attached to the request, so the people who decide see the exact wording.

## How it works

1. Both commits are taken from git with `git archive`. Uncommitted changes in the working tree are not part of either version.
2. Each version of the folder is assembled into one Markdown document with the same steps and plugins as `ope export`. Embeds are expanded, Dataview queries run and Meta Bind values are filled in, so the two documents are compared as they appear in the PDF.
3. The two documents are split into blocks at blank lines (paragraphs, list blocks, tables, headings, code blocks) and the blocks are compared.
4. An unchanged block is kept as it is. A block that changed is compared word by word, and in lists line by line, and gets inline `<ins>` and `<del>` marks. A block that only exists in one version is shown as a whole inserted or removed block.
5. The result goes through the rest of the export (callouts, links, numbering, table of contents) and is laid out with the [`redline` template](styling.md).

## What the reader sees

![Redline of the example policy](../img/redline/overview.png)

- Inserted words: green, underlined, on a light green background.
- Removed words: red, struck through, on a light red background.
- Inserted blocks: a green box with a green bar on the left.
- Removed blocks: a red box with a red bar, all text struck through. A removed heading is shown as bold text, so it does not get a number and does not show up in the table of contents.
- Changed headings: the word changes are shown in the heading and in the table of contents.
- The subtitle and the version label show the two short commit hashes, for example `Redline: f240681 -> d1d04f5`.

Some kinds of change are not shown well yet, for example inserted table rows and changes inside code blocks. [What changes look like](changes.md) shows every case with a screenshot and links the open issues.

## In this section

| Page | Content |
| ---- | ------- |
| [Usage](usage.md) | The command and every flag, default names, one document or a folder, and CI workflows. |
| [Comparing versions](compare.md) | Tags, branches, commits and `HEAD~n`, releases, pull requests, the history of one note, and versions outside git. |
| [What changes look like](changes.md) | Words, paragraphs, headings, lists, tables, callouts, images, embeds, properties and Dataview, each with a screenshot. |
| [Styling the redline](styling.md) | The `redline` template, the elements and classes a redline emits, and how to restyle them. |
| [Limitations and tips](limitations.md) | What a redline does not show, and how to get a clean one. |
