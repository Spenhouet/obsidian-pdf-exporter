---
title: Dataview
description: Dataview TABLE and LIST queries rendered to static tables and lists.
---

# Dataview

The `dataview` plugin runs [Dataview](https://github.com/blacksmithgu/obsidian-dataview) queries at export time and writes the result as a Markdown table or list. The project notes queried here look like this:

````markdown
--8<-- "examples/_notes/Projects/Website relaunch.md"
````

<div class="ope-example" markdown>
<div markdown>
<p class="ope-label">Markdown</p>

````markdown
--8<-- "examples/dataview/dataview.md"
````

</div>
<div markdown>
<p class="ope-label">PDF</p>

![A table and a list built from the query results](../img/features/dataview.png)

</div>
</div>

## Supported queries

- `TABLE` (with `WITHOUT ID`) and `LIST`.
- `FROM #tag` and `FROM "folder"`, combined with `AND` and `OR`, negated with `-`.
- `WHERE` with `field = "x"`, `field != "x"`, `NOT`, `AND`, `OR` and bare fields.
- `SORT field ASC|DESC` and `LIMIT n`.

`TASK`, `CALENDAR` and `dataviewjs` blocks are replaced with a placeholder text. Other queries are left as they are.

The query runs over the whole vault (the folder with `.obsidian`, or the git repository). Without a vault root the blocks stay as they are.
