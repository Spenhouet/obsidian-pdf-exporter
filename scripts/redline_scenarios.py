#!/usr/bin/env python
"""Build a small git vault with hard cases for ``ope redline`` and ``--blame``.

The vault holds a ``Handbook`` folder that is changed over several commits. The
baseline is tagged ``v1.0`` and the revised version ``v2.0``, so

    ope redline Handbook --from-commit v1.0 --to-commit v2.0

shows every scenario at once. The commits have different authors and dates, so a
blame of ``v2.0`` has several groups.

Run from the repository root:

    uv run python scripts/redline_scenarios.py /path/to/new/vault

The target folder must not exist yet.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image
from PIL import ImageDraw

# ---------------------------------------------------------------------------
# Shared text
# ---------------------------------------------------------------------------

LONG_V1 = (
    "This handbook describes how documents are created, reviewed, approved and "
    "released. It applies to all controlled documents of the organisation, including "
    "procedures, work instructions, forms and templates. Every document has one owner, "
    "who keeps the content correct and starts a review at least every two years. A "
    "document that is not reviewed within that period is marked as overdue in the "
    "register, and the owner is reminded by the quality team. Changes to a document "
    "are made in a draft, which is reviewed by at least one person who did not write "
    "it. The reviewer checks the content against the requirements and the current "
    "practice, and records the result in the review record."
)
LONG_V2 = (
    "This handbook describes how documents are created, reviewed, approved and "
    "released. It applies to all controlled documents of the organisation, including "
    "procedures, work instructions and forms. Every document has one named owner, "
    "who keeps the content correct and starts a review at least every three years. A "
    "document that is not reviewed within that period is marked as overdue in the "
    "register, and the owner is reminded promptly by the quality team. Changes to a "
    "document are made in a draft, which is reviewed by at least two people who did "
    "not write it. The reviewer checks the content against the requirements, the risk "
    "assessment and the current practice, and records the result in the review record."
)

REWRAP_V1 = """Documents are written in plain language. Sentences are short, and each
paragraph covers one topic. Terms that have a defined meaning are listed in the
glossary at the end of this handbook."""
REWRAP_V2 = """Documents are written in plain language. Sentences are short,
and each paragraph covers one topic. Terms that have a defined meaning
are listed in the glossary at the end of this handbook."""

MOVED_PARA = (
    "Training records show who was trained on which revision of a document. They are "
    "kept together with the personnel file and are checked during internal audits."
)

MOVED_EDIT_V1 = (
    "Superseded revisions are moved to the archive folder on the day the new revision "
    "becomes effective. They stay readable for the retention period but can no longer "
    "be selected for new work."
)
MOVED_EDIT_V2 = (
    "Superseded revisions are moved to the archive on the day the new revision becomes "
    "effective. They stay readable for the full retention period but can no longer be "
    "selected for new work or training."
)

FILLER = [
    "Each section of a document starts with a short statement of what it covers. "
    "Readers who only need one part of a document can then find it quickly, and "
    "reviewers can check that every requirement is covered by exactly one section.",
    "Figures and tables have a caption that says what they show. A table that continues "
    "on the next page repeats its header row, so every page can be read on its own.",
    "Cross references point to a section by its heading, not by its number, because the "
    "numbers change when a section is added or removed in a later revision.",
]

GLOSSARY_V1 = [
    ("Approval", "The signed decision that a document may be released."),
    ("Archive", "The storage area for superseded and withdrawn documents."),
    ("Audit", "A planned check that procedures are followed as written."),
    ("Author", "The person who writes or changes the draft of a document."),
    ("Baseline", "The approved state of a document at a given point in time."),
    ("Change request", "A written request to change an approved document."),
    ("Controlled copy", "A copy whose distribution is tracked by the owner."),
    ("Deviation", "A planned and approved departure from a procedure."),
    ("Distribution list", "The people who receive a document when it is released."),
    ("Draft", "A version of a document that is not yet approved."),
    ("Effective date", "The day from which a document must be followed."),
    ("Form", "A document with fields that is filled in to create a record."),
    ("Owner", "The person responsible for the content of a document."),
    ("Periodic review", "The review of a document at a fixed interval."),
    ("Procedure", "A document that describes how an activity is carried out."),
    ("Record", "A document that shows that an activity took place."),
    ("Register", "The list of all controlled documents and their status."),
    ("Release", "The step that makes an approved document available."),
    ("Retention period", "The time for which a record must be kept."),
    ("Review", "The check of a draft against requirements and practice."),
    ("Reviewer", "The person who checks a draft before approval."),
    ("Revision", "A numbered, approved state of a document."),
    ("Signature", "The mark of a person that confirms a decision."),
    ("Superseded", "Replaced by a newer revision of the same document."),
    ("Template", "A document that gives the structure for new documents."),
    ("Training", "The activity that makes a person able to follow a document."),
    ("Uncontrolled copy", "A copy that is not updated when a document changes."),
    ("Version", "Any saved state of a document, approved or not."),
    ("Withdrawal", "The step that removes a document from use."),
    ("Work instruction", "A document that describes a single task in detail."),
    ("Workflow", "The ordered steps from draft to released document."),
    ("Validity", "The period during which a revision is in use."),
]
GLOSSARY_V2_EDITS = {
    "Approval": "The signed and dated decision that a document may be released.",
    "Archive": "The storage area for superseded or withdrawn documents.",
    "Audit": "A planned, independent check that procedures are followed as written.",
    "Author": "The person who writes or changes a draft.",
    "Baseline": "The approved state of a document at a given date.",
    "Change request": "A written and justified request to change an approved document.",
    "Controlled copy": "A copy whose distribution is tracked by the document owner.",
    "Deviation": "A planned, time-limited and approved departure from a procedure.",
    "Distribution list": "The people and roles who receive a document when it is released.",
    "Draft": "A version of a document that is not approved yet.",
    "Effective date": "The date from which a document must be followed.",
    "Form": "A document with fields that is completed to create a record.",
    "Owner": "The person accountable for the content of a document.",
    "Periodic review": "The review of a document at a fixed, documented interval.",
    "Procedure": "A document that describes how a process is carried out.",
    "Record": "A document that gives evidence that an activity took place.",
    "Register": "The list of all controlled documents with their status.",
    "Release": "The step that makes an approved document available for use.",
    "Retention period": "The minimum time for which a record must be kept.",
    "Review": "The check of a draft against the requirements and practice.",
    "Reviewer": "The independent person who checks a draft before approval.",
    "Revision": "A numbered and approved state of a document.",
    "Signature": "The handwritten or electronic mark of a person that confirms a decision.",
    "Superseded": "Replaced by a later revision of the same document.",
    "Template": "A document that defines the structure for new documents.",
    "Training": "The activity that enables a person to follow a document.",
    "Uncontrolled copy": "A copy that is not updated when the document changes.",
    "Version": "Any saved state of a document, whether approved or not.",
    "Withdrawal": "The step that removes a document from use permanently.",
    "Work instruction": "A document that describes one task in detail.",
    "Workflow": "The ordered steps from draft to released and effective document.",
    "Validity": "The period during which a revision is valid.",
}


def glossary(edits: dict[str, str] | None) -> str:
    lines = ["The terms below have a defined meaning in this handbook.", ""]
    for term, definition in GLOSSARY_V1:
        text = (edits or {}).get(term, definition)
        lines.append(f"- **{term}**: {text}")
    return "\n".join(lines) + "\n"


INTRO = "Scenario corpus for redline and blame output. Each chapter holds hard cases.\n"

# ---------------------------------------------------------------------------
# Version 1 (baseline)
# ---------------------------------------------------------------------------

PURPOSE_V1 = f"""---
doc_id: HB-001
revision: 3
owner: Quality Team
---
This handbook is the controlled document `VIEW[{{doc_id}}][text]`, revision `VIEW[{{revision}}][text]`, owned by the `VIEW[{{owner}}][text]`.

## Purpose

{LONG_V1}

{REWRAP_V1}

Each controlled document must be reviewed before release and approved by its owner.

The current list of documents is kept in the [document register](https://example.com/register/2025).

Records are kept for ten years.[^retention]

[^retention]: The retention period starts at the end of the calendar year.

## Scope

The handbook covers documents in paper and electronic form. It does not cover email, chat messages or personal notes.

{MOVED_PARA}

{FILLER[0]}
"""

PROCEDURES_V1 = f"""## Document Review

A review starts when the author marks the draft as ready. The owner selects the reviewers and sets a due date.

Reviewers may add comments directly in the draft. Comments that are not resolved block the approval until the author answers them.

Reviews by email are not accepted, because the comments cannot be traced to the draft they refer to.

### Review checklist

- Check the document ID
- Check the revision
  - The revision number is incremented
  - The change history is filled in
  - The old revision is archived
- Check the approvals
- Check the distribution list

> [!warning] Before release
> The document must not be released before all approvals are present.

> [!note] Paper review
> A printed copy may be used for the review if the comments are transferred to the draft.

### Release tasks

- [ ] Training is planned
- [ ] Old copies are withdrawn
- [x] Register entry is updated

### Escalation

Disagreements between author and reviewer are escalated to the owner.

## Numbering

Every document gets a number when its first draft is created.

```text
DOC-<area>-<number>
area:   QA, RD, OP
number: 4 digits
```

{FILLER[1]}

## Archiving

{FILLER[2]}
"""

RECORDS_V1 = f"""## Record types

| Record        | Owner | Retention |
| ------------- | ----- | --------- |
| Training      | HR    | 10 years  |
| Review        | QA    | 10 years  |
| Audit report  | QA    | 15 years  |
| Calibration   | OP    | 10 years  |

## Storage locations

| Location      | Access          |
| ------------- | --------------- |
| Document system | All staff (read) |
| Archive server  | Quality team     |

{MOVED_EDIT_V1}

## Workflow

![[workflow-v1.png|420]]

```mermaid
flowchart LR
  A[Draft] --> B[Review] --> C[Release]
```

## Open records

```dataview
TABLE status, owner
FROM "_records"
SORT file.name ASC
```

## Paper records

Some records are still kept on paper. This section describes how they are handled until they are replaced by electronic records.

Paper records are written in permanent ink. Corrections are made by crossing out the old entry with a single line, so that it stays readable, and by adding the date and the initials of the person who made the correction.

Completed paper records are collected by the record owner at the end of each month. They are stored in a locked cabinet in the archive room, sorted by record type and date.

### Scanning

Paper records may be scanned to make them easier to find. The scan is checked against the original for completeness and readability before it is filed.

The original is kept for the full retention period even after scanning, because the scan alone is not accepted as evidence.
"""

RECORD_FILES_V1 = {
    "_records/REC-01 Supplier audit.md": "---\nstatus: open\nowner: QA\n---\nAudit of a supplier.\n",
    "_records/REC-02 Training plan.md": "---\nstatus: open\nowner: HR\n---\nAnnual plan.\n",
    "_records/REC-03 Calibration.md": "---\nstatus: closed\nowner: OP\n---\nScale check.\n",
}

# ---------------------------------------------------------------------------
# Version 2 (revised)
# ---------------------------------------------------------------------------

PURPOSE_V2 = f"""---
doc_id: HB-001
revision: 4
owner: Quality Team
---
This handbook is the controlled document `VIEW[{{doc_id}}][text]`, revision `VIEW[{{revision}}][text]`, owned by the `VIEW[{{owner}}][text]`.

## Purpose

{LONG_V2}

{REWRAP_V2}

Each controlled document must be reviewed before release and **approved** by its owner.

The current list of documents is kept in the [document register](https://example.com/register/2026).

Records are kept for ten years.[^retention]

[^retention]: The retention period starts on the date of the last entry in the record.

## Scope

The handbook covers documents in paper and electronic form. It does not cover email, chat messages or personal notes.

Documents supplied by customers or authorities are registered but are not changed. Their owner is the person who received them.

{FILLER[0]}
"""

PROCEDURES_V2 = f"""## Document Review and Approval

A review starts when the author marks the draft as ready. The owner selects the reviewers and sets a due date.

Reviewers may add comments directly in the draft. Comments that are not resolved block the approval until the author answers them.

Approval is given in the document system with an electronic signature. The approver confirms that the review is complete and that all comments are resolved.

### Review checklist

- Check the document ID
- Check the revision
  - The revision number is incremented
  - The effective date is set
  - The change history is filled in
- Check the distribution list
- Check the approvals
- Check the training needs

> [!warning] Before release
> The document must not be released before all required approvals are recorded in the document system.

> [!tip] Faster reviews
> Small reviews go faster when the author names the sections that changed.

### Release tasks

- [x] Training is planned
- [ ] Affected records are identified
- [ ] Old copies are withdrawn from all sites
- [x] Register entry is updated

## Escalation

Disagreements between author and reviewer are escalated to the owner.

## Numbering

Every document gets a number when its first draft is created.

```text
DOC-<area>-<number>
area:   QA, RD, OP
number: 5 digits, zero padded
```

{FILLER[1]}

## Templates

New documents are created from the template of their type. A template is itself a controlled document and follows the same review and approval.

## Archiving

{FILLER[2]}

{MOVED_EDIT_V2}

## Training

{MOVED_PARA}
"""

RECORDS_V2 = """## Record types

| Record        | Owner | Retention |
| ------------- | ----- | --------- |
| Training      | HR    | 10 years  |
| Review        | QA    | 15 years  |
| Calibration   | OP    | 10 years  |
| Supplier evaluation | Purchasing | 10 years |

## Storage locations

| Location      | Access          | Backup |
| ------------- | --------------- | ------ |
| Document system | All staff (read) | Daily |
| Archive server  | Quality team     | Weekly |

## Workflow

![[workflow-v2.png|420]]

```mermaid
flowchart LR
  A[Draft] --> B[Review] --> D[Approve] --> C[Release]
```

## Open records

```dataview
TABLE status, owner
FROM "_records"
SORT file.name ASC
```
"""

RECORD_FILES_V2 = {
    "_records/REC-01 Supplier audit.md": "---\nstatus: closed\nowner: QA\n---\nAudit of a supplier.\n",
    "_records/REC-04 Supplier evaluation.md": (
        "---\nstatus: open\nowner: Purchasing\n---\nEvaluation of a new supplier.\n"
    ),
}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def workflow_image(path: Path, steps: list[str]) -> None:
    """Draw a simple left-to-right flow of boxes."""
    w, h = 900, 180
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    box_w = (w - 40 - (len(steps) - 1) * 40) // len(steps)
    x = 20
    for i, step in enumerate(steps):
        d.rounded_rectangle([x, 50, x + box_w, 130], radius=12, outline="#33415c", width=4)
        tw = d.textlength(step, font_size=28)
        d.text((x + (box_w - tw) / 2, 74), step, fill="#1a1a1a", font_size=28)
        if i < len(steps) - 1:
            ax = x + box_w
            d.line([ax + 6, 90, ax + 34, 90], fill="#33415c", width=4)
            d.polygon([(ax + 34, 82), (ax + 34, 98), (ax + 40, 90)], fill="#33415c")
        x += box_w + 40
    img.save(path)


def write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def commit(root: Path, message: str, author: str, email: str, date: str) -> None:
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME=author,
        GIT_AUTHOR_EMAIL=email,
        GIT_AUTHOR_DATE=date,
        GIT_COMMITTER_NAME=author,
        GIT_COMMITTER_EMAIL=email,
        GIT_COMMITTER_DATE=date,
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, check=True, env=env)


def tag(root: Path, name: str) -> None:
    subprocess.run(["git", "tag", name], cwd=root, check=True)


def build(root: Path) -> None:
    """Create the vault and its history in ``root``."""
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "app.json").write_text("{}\n", encoding="utf-8")
    att = root / "Handbook" / "_attachments"
    att.mkdir(parents=True)
    workflow_image(att / "workflow-v1.png", ["Draft", "Review", "Release"])

    # 1. Initial draft: purpose and procedures.
    write(root, {"Handbook/Handbook.md": INTRO})
    write(
        root,
        {
            "Handbook/About this Handbook/About this Handbook.md": PURPOSE_V1,
            "Handbook/Procedures/Procedures.md": PROCEDURES_V1,
        },
    )
    commit(
        root,
        "Add first draft of the handbook",
        "Alex Example",
        "alex@example.com",
        "2025-09-03T10:00:00+02:00",
    )

    # 2. Records and glossary by a second author.
    write(
        root,
        {
            "Handbook/Records/Records.md": RECORDS_V1,
            "Handbook/Terms and Definitions/Terms and Definitions.md": glossary(None),
        },
    )
    write(root, RECORD_FILES_V1)
    commit(
        root,
        "Add records chapter and glossary",
        "Sam Sample",
        "sam@example.com",
        "2025-11-18T14:30:00+01:00",
    )
    tag(root, "v1.0")

    # 3. Revision of purpose and procedures.
    write(
        root,
        {
            "Handbook/About this Handbook/About this Handbook.md": PURPOSE_V2,
            "Handbook/Procedures/Procedures.md": PROCEDURES_V2,
        },
    )
    commit(
        root,
        "Revise review procedure and move training text",
        "Kim Reviewer",
        "kim@example.com",
        "2026-03-09T09:15:00+01:00",
    )

    # 4. Records, image and glossary updates.
    workflow_image(att / "workflow-v2.png", ["Draft", "Review", "Approve", "Release"])
    (att / "workflow-v1.png").unlink()
    write(
        root,
        {
            "Handbook/Records/Records.md": RECORDS_V2,
            "Handbook/Terms and Definitions/Terms and Definitions.md": glossary(GLOSSARY_V2_EDITS),
        },
    )
    (root / "_records" / "REC-02 Training plan.md").unlink()
    write(root, RECORD_FILES_V2)
    commit(
        root,
        "Update records, workflow figure and glossary",
        "Alex Example",
        "alex@example.com",
        "2026-05-21T16:40:00+02:00",
    )
    tag(root, "v2.0")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", type=Path, help="Folder to create the vault in")
    args = parser.parse_args()
    if args.target.exists():
        print(f"{args.target} exists already", file=sys.stderr)
        return 1
    build(args.target)
    print(f"Scenario vault written to {args.target} (tags v1.0 and v2.0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
