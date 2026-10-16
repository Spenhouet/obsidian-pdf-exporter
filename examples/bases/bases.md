```base
filters:
  and:
    - file.hasTag("project")
views:
  - type: table
    name: Projects
    order:
      - file.name
      - owner
      - status
      - due
    sort:
      - property: due
        direction: ASC
  - type: list
    name: Open
    filters:
      and:
        - status != "done"
```
