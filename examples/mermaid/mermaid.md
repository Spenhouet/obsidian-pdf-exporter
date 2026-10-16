```mermaid
flowchart LR
    A[Notes] --> B{Export}
    B -->|PDF| C[Readers]
    B -->|Redline| D[Reviewers]
```

```mermaid
sequenceDiagram
    Author->>ope: export ./Notes
    ope->>Author: handbook.pdf
```
