---
id: 0602
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.347130+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Never hand-author ADR-0053 glossary term ULIDs in docs/wiki/terms/

Glossary terms under `docs/wiki/terms/` are proposed by the term loop, not fabricated during feature work — even when a new feature clearly needs a canonical term.

Example: instead of inventing a ULID for an ultra-review tier, let the `term_proposer_loop` create it.

**Why:** a manually-invented ULID breaks the ADR-0053 living-artifact discipline that keeps term anchors in sync with generated docs.
