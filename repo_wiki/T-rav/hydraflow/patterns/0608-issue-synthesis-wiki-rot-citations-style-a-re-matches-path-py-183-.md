---
id: 0608
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.353398+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# wiki_rot_citations _STYLE_A_RE matches path.py:183 line refs as symbol cites

`_STYLE_A_RE` in `src/wiki_rot_citations.py` is `\b([\w./-]+\.py):(\w+)` — `\w+` matches digits, so line refs (`base_background_loop.py:141`) get extracted as symbol cites. Any extension of cite extraction must exclude numeric-symbol/placeholder candidates first.

Example: `verify_cite_ast` can never resolve a numeric symbol, so `WikiRotDetectorLoop` reports these broken forever and escalates after 3 attempts.

**Why:** without excluding line refs, new scan roots trigger a permanent false-positive escalation storm.
