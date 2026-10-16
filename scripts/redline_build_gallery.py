"""Build gallery.html (self-contained) and gallery.pdf from the crops."""

import base64
import json
import sys
from pathlib import Path

import weasyprint

OUT = Path(sys.argv[1])
crops = json.loads((OUT / "crops.json").read_text())

OPTIONS = [
    ("a", "A · Blackline",
     "Classic legal blackline. Insertions blue with a double underline, deletions vermilion and struck, "
     "moves purple with double marks and a “Moved to/from” label, one black change bar per change group "
     "in the left margin. No backgrounds, no boxes.",
     ["Familiar to auditors and legal reviewers", "Greyscale-safe: underline vs. strike carry the meaning",
      "Compact; the document keeps its own layout", "Cheapest to build and maintain"],
     ["Heavily edited pages get dense", "Long deletions stay at full length in place",
      "What happened to a block (replaced, moved) is only in small labels"],
     "Low: CSS on the shared engine, 0.3 / 0.5 / 1.5 PD (guess)"),
    ("b", "B · Track changes with balloons",
     "Word-processor look: the inline marks of A plus one numbered balloon per change group in a right "
     "margin column (what happened, counts, formatting, link targets, rows and columns, task state; author and date "
     "from blame are a prepared hook, not wired yet).",
     ["Reviewer sees the kind of change at a glance", "Familiar from word processors",
      "Natural place for author, date and comments"],
     ["Text column narrows to ~120 mm", "Balloons drift down when changes are close together",
      "Margin floats depend on WeasyPrint layout details"],
     "Medium: 0.8 / 1.5 / 3.5 PD (guess)"),
    ("c", "C · Clean copy with change notes",
     "Text reads as the new version. Insertions lightly highlighted; each deletion leaves a ⌫n mark whose "
     "words appear as a compact note at the foot of the page; long deletions go to an annex. Change bars "
     "with change numbers Cn in the margin and a change index (with page numbers) at the start.",
     ["Reads as the text that gets approved", "Change index is an auditable list with pages",
      "Scales to many changes without clutter in the text"],
     ["Deleted text is not in place (foot notes / annex)", "Note area fills up on pages with 30+ changes",
      "Most transform code of all options"],
     "Medium to high: 1.5 / 2.5 / 5 PD (guess)"),
    ("d", "D · Side by side",
     "Unchanged text full width. Each change group becomes a two-column Before | After table with word "
     "marks in both columns; a replaced block sits next to its replacement, inserted/deleted blocks face "
     "an empty cell.",
     ["Unambiguous before/after per block", "Best for tables, code and figures",
      "No need to read struck text"],
     ["Half-width columns cramp wide tables and long lists", "Document grows (headings appear twice)",
      "Footnotes of the old side shown inline"],
     "Medium: 0.8 / 1.5 / 3 PD (guess)"),
    ("e", "E · Diff blocks",
     "Code-review look: a header per change group (section and summary), the removed version with a "
     "− gutter on an orange tint and the added version with a + gutter on a blue tint, changed words "
     "in a stronger tint. Lists, tables and code show only the changed items twice.",
     ["Very explicit, familiar to engineers", "Per item / row / line for lists, tables, code",
      "Symbols (− + ⇄) carry meaning without colour"],
     ["Changed paragraphs are printed twice", "Tints cost toner and look technical",
      "Longest output of all options"],
     "Medium: 0.8 / 1.5 / 3 PD (guess)"),
]

BLAME = [
    ("export-margin", "Variant 1: margin column (portrait) on ope export --blame",
     "Narrow column in a wider right margin: short hash, initials, date; a bracket per group of "
     "blocks from the same commit; mark shade by age (darker = newer)."),
    ("export-wide", "Variant 2: wide column (landscape) on ope export --blame",
     "Same text width on a landscape page; the column adds author name, commit subject and a thick "
     "age strip."),
    ("export-key", "Commit key added before the table of contents", "Lists the commits with their age shade."),
    ("redline-a-margin", "ope redline --blame (style A + margin column)",
     "Blame of the new version; commits inside the compared range are highlighted in amber."),
    ("redline-e-wide", "ope redline --blame (style E + wide column)",
     "“IN RANGE” marks the commits between the two refs."),
    ("vault-margin", "Real vault folder, variant 1 (local only, not for publication)", ""),
    ("vault-wide", "Real vault folder, variant 2 (local only, not for publication)", ""),
]


def img(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def build(pdf: bool) -> str:
    cards = ""
    for key, name, desc, pros, cons, effort in OPTIONS:
        cards += f"""
<div class="card"><h3>{name}</h3><p>{desc}</p>
<div class="pc"><div><b>Pros</b><ul>{''.join(f'<li>{p}</li>' for p in pros)}</ul></div>
<div><b>Cons</b><ul>{''.join(f'<li>{c}</li>' for c in cons)}</ul></div></div>
<p class="eff">Effort on top of the shared engine: {effort}</p>
<p class="files">PDF: <a href="pdf/redline-{key}.pdf">redline-{key}.pdf</a></p></div>"""
    sections = ""
    for key, title in crops["scenarios"]:
        cols = ""
        for okey, name, *_ in OPTIONS:
            rel = crops["crops"].get(key, {}).get(f"redline-{okey}")
            src = img(OUT / rel) if rel else ""
            cols += f'<figure><figcaption>{name}</figcaption>{f"<img src={chr(34)}{src}{chr(34)}>" if src else "<p>not found</p>"}</figure>'
        sections += f'<section class="scen"><h2>{title}</h2><div class="row">{cols}</div></section>'
    blame = ""
    for key, title, desc in BLAME:
        p = OUT / "blame" / f"{key}.png"
        if p.exists():
            blame += f'<figure class="bl"><figcaption><b>{title}</b><br>{desc}</figcaption><img src="{img(p)}"></figure>'
    css = """
body { font-family: Arial, 'Liberation Sans', sans-serif; color: #1a1a1a; margin: 0; padding: 24px 32px; background: #f6f7f8; }
h1 { font-size: 26px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 28px 0 10px; }
p.lead { max-width: 1100px; color: #444; line-height: 1.45; }
.cards { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.card { background: white; padding: 12px 14px; border-top: 3px solid #26292d; font-size: 13px; line-height: 1.4; }
.card h3 { margin: 0 0 6px; font-size: 15px; } .pc { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.pc ul { margin: 2px 0 0 16px; padding: 0; } .eff { color: #5f6670; } .files { font-size: 12px; }
.row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; align-items: start; }
figure { margin: 0; background: white; padding: 6px; } figcaption { font-size: 12px; font-weight: bold; color: #5f6670; margin-bottom: 4px; }
figure img { width: 100%; display: block; border: 1px solid #e3e5e8; }
.blame { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; } figure.bl figcaption { font-weight: normal; }
.rec { background: white; border-left: 4px solid #0b57b0; padding: 10px 14px; max-width: 1100px; line-height: 1.45; }
"""
    if pdf:
        css += """
@page { size: A3 landscape; margin: 10mm; }
body { padding: 0; background: white; font-size: 11px; }
.cards { grid-template-columns: repeat(5, 1fr); } .card { border: 1px solid #ddd; font-size: 10px; }
section.scen { break-before: page; } section.scen h2 { margin-top: 0; }
.row { display: flex; gap: 6px; } .row figure { flex: 1; max-height: 255mm; overflow: hidden; }
.blame { display: block; } figure.bl { break-inside: avoid; } figure.bl + figure.bl { break-before: page; } figure.bl img { max-height: 240mm; width: auto; max-width: 100%; }
a { color: inherit; text-decoration: none; }
"""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Redline Design Options</title><style>{css}</style></head><body>
<h1>Redline design options</h1>
<p class="lead">Five looks for <code>ope redline</code>, all rendered from the same scenario vault (two commits apart, see
<code>scripts/redline_scenarios.py</code>) with the same improved diff engine. Every option gets the same summary block
(compared sources, counts, changed sections with page numbers, commits in range), change marks in the table of contents
(count per section, <i>new</i>, struck <i>removed</i> entries) and linked move labels. Colours: blue insertions,
vermilion deletions, purple moves; each also has a non-colour cue (underline, strike, symbol, position).
Crops show the same scenario for each option side by side.</p>
<div class="rec"><b>Recommendation:</b> make <b>A (Blackline)</b> the default and offer <b>C (Clean copy with change notes)</b> as the
approval view; keep D and E as optional styles for technical documents if demand appears. Balloons (B) mainly pay off together with the blame data.</div>
<h2>Options</h2><div class="cards">{cards}</div>
{sections}
<section class="scen"><h2>Blame column (two layout variants)</h2><div class="blame">{blame}</div></section>
</body></html>"""


(OUT / "gallery.html").write_text(build(False), encoding="utf-8")
weasyprint.HTML(string=build(True), base_url=str(OUT)).write_pdf(str(OUT / "gallery.pdf"))
print("ok", (OUT / "gallery.html").stat().st_size // 1024, "KB")
