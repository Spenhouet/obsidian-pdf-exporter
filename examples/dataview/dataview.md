```dataview
TABLE status, owner, due
FROM #project
SORT due ASC
```

```dataview
LIST
FROM "_notes/Projects"
WHERE status != "done"
```
