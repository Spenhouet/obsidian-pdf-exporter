```dataview
TABLE status, owner, due
FROM #project
SORT due ASC
```

```dataview
TABLE WITHOUT ID file.link AS "Project", due - date(today) AS "Time left"
FROM #project
WHERE status != "done"
SORT due ASC
```

```dataview
TABLE rows.file.link AS "Projects", length(rows) AS "Count"
FROM #project
GROUP BY status
```
