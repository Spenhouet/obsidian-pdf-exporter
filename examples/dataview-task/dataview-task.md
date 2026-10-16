```dataview
TASK
FROM "_notes/Journal"
WHERE !completed
GROUP BY file.link
```

```dataview
TASK
FROM "_notes/Journal"
WHERE due AND due < date(2026-04-05)
```
