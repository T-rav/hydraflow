---
id: 0599
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.343950+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Strip prose-colliding aliases in validate_draft, don't reject the term

In `src/ubiquitous_language.py`, `validate_draft` should strip an alias that collides with live wiki prose rather than hard-rejecting the whole draft — reserve hard-reject for canonical-name collisions only.

Example: pass `wiki_root` into `validate_draft`, defaulted to optional so existing callers work unchanged. See also: patterns — Factor one shared word-boundary matcher.

**Why:** a colliding alias is a naming detail, not an identity conflict — rejecting the whole term throws away a valid definition.
