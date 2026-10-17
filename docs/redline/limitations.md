---
title: Limitations and tips
description: What a redline does not show, the known issues, and how to write and commit notes so that the redline stays clean.
---

# Limitations and tips

## What a redline does not show

- Uncommitted changes. Both versions come from git. Commit first, or the working tree is ignored.
- Properties that the text does not show. The properties block is not part of the PDF, so a change of `status: draft` to `status: approved` is invisible unless a Meta Bind field or a Dataview table shows it. See [Properties and Meta Bind](changes.md#properties-and-meta-bind).
- Moves of short or rewritten text. A paragraph counts as moved when it has at least six words and is nearly the same in both places; a list item when it is unchanged and stays in the same list. Other text is shown as removed at the old place and inserted at the new one. See [Moved text](changes.md#moved-text).
- Notes outside `ROOT`, unless they are embedded or queried. A change in an embedded note or in a note a Dataview query reads does show up, since the embed and the query run before the comparison.
- Layout. Template changes, page breaks and landscape pages are not compared. Wide tables and figures stay on portrait pages in a blackline redline.
- A changed image file that keeps its name. The comparison reads the Markdown, so an image that was replaced by a new file with the same name is shown unmarked, in its new version. Give a new image a new file name, or mention the change in the text.
- Changes inside a diagram. A changed Mermaid diagram is shown as the old and the new drawing, not with marks inside the drawing.

## Known issues

| Case | Issue |
| ---- | ----- |
| Two folders or two notes cannot be compared without git | [#92](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/92) |

## Tips for a clean redline

- Keep one sentence per paragraph change. The comparison works per block, so a small edit in a long paragraph is shown word by word, while a rewrite of the whole paragraph is shown as removed and inserted.
- Separate unrelated edits by an unchanged paragraph or list item where you can. Each group of neighbouring changes gets one bar in the margin and one line in the summary.
- Reflowing text and re-padding tables is fine: line breaks and spaces inside a paragraph and the padding of table cells are not changes. With hard line breaks (the default) a moved line break still moves the break in the PDF.
- Avoid `~~strikethrough~~` in controlled documents. It renders as `del`, the same element as removed text, and looks like a removal in the redline.
- Use tags for releases (`v1.0.0`, `v1.1.0`). Then a redline of any two releases is one command, and the CI recipes in [Usage](usage.md#in-ci) work without changes.
- For a pull request, compare against the merge base, not against the tip of `main`. See [Comparing versions](compare.md#a-branch-or-pull-request-against-main).
- Look at the diffed Markdown when a mark looks wrong: `--debug` keeps `redline_assembled.md` in the build folder next to the PDF.
- A redline of a new folder is one long insertion. Compare from the first commit that has the folder, or make a normal export instead.
