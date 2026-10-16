---
title: Limitations and tips
description: What a redline does not show, the known issues, and how to write and commit notes so that the redline stays clean.
---

# Limitations and tips

## What a redline does not show

- Uncommitted changes. Both versions come from git. Commit first, or the working tree is ignored.
- Properties that the text does not show. The properties block is not part of the PDF, so a change of `status: draft` to `status: approved` is invisible unless a Meta Bind field or a Dataview table shows it. See [Properties and Meta Bind](changes.md#properties-and-meta-bind).
- Moves as moves. A moved paragraph is shown as removed at the old place and inserted at the new one. See [Moved text](changes.md#moved-text).
- Notes outside `ROOT`, unless they are embedded or queried. A change in an embedded note or in a note a Dataview query reads does show up, since the embed and the query run before the comparison.
- Layout. Template changes, page breaks and landscape pages are not compared. Wide tables and figures stay on portrait pages in a redline.
- Changed diagrams. A changed Mermaid block is not drawn and shows its source with the marks as text, like a code block ([#81](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/81)).

## Known issues

| Case | Issue |
| ---- | ----- |
| An inserted or removed table row, or a wider column, breaks the table | [#80](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/80) |
| Changes inside a code block or a Mermaid diagram show `<del>` and `<ins>` as text | [#81](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/81) |
| A replaced paragraph is word-diffed even when it has little in common with the old one | [#82](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/82) |
| An inserted or removed callout loses its body to a separate box | [#83](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/83) |
| A replaced image is not marked | [#84](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/84) |
| Checking a task shows the checkbox brackets as text | [#85](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/85) |
| A changed heading level is not shown | [#86](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/86) |
| A changed footnote leaves two empty boxes | [#87](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/87) |
| The title block shows the commit range twice | [#88](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/88) |
| A changed paragraph or list item next to an inserted or removed one loses its word-level diff | [#89](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/89) |
| With `.` as `ROOT` the default file name is `export_redline.pdf` | [#91](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/91) |

## Tips for a clean redline

- Keep one sentence per paragraph change. The comparison works per block, so a small edit in a long paragraph is shown word by word, while a rewrite of the whole paragraph is shown as removed and inserted.
- Separate unrelated edits by an unchanged paragraph or list item where you can. Neighbouring changes are grouped and then shown as whole blocks ([#89](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/89)).
- Do not reflow text. A moved line break makes the words around it show up as removed and inserted, and with hard line breaks (the default) it also moves the break in the PDF. A reformatted table (new padding) breaks the table, see [#80](https://github.com/Spenhouet/obsidian-pdf-exporter/issues/80).
- Avoid `~~strikethrough~~` in controlled documents. It renders as `del`, the same element as removed text, and looks like a removal in the redline.
- Use tags for releases (`v1.0.0`, `v1.1.0`). Then a redline of any two releases is one command, and the CI recipes in [Usage](usage.md#in-ci) work without changes.
- For a pull request, compare against the merge base, not against the tip of `main`. See [Comparing versions](compare.md#a-branch-or-pull-request-against-main).
- Look at the diffed Markdown when a mark looks wrong: `--debug` keeps `redline_assembled.md` in the build folder next to the PDF.
- A redline of a new folder is one long insertion. Compare from the first commit that has the folder, or make a normal export instead.
