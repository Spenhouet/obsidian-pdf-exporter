```dataview
LIST
FROM "_notes/Projects"
WHERE status != "done"
```

```dataview
LIST owner + " (" + status + ")"
FROM #project
SORT file.name
```

```dataview
LIST rows.file.link
FROM #project
GROUP BY owner
```
