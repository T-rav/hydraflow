---
id: 0589
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.332263+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Keep make audit out of quality-lite; gate it by touched-path instead

Keep `make audit` (the Principles Audit) out of `make quality-lite`, the pre-push hook's fast common-path target; gate `make audit` behind a path-triggered conditional instead.

Example: trigger on changes to `Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, or ADR-0044.

**Why:** folding audit into quality-lite would add ~1–3 min to every push; path-triggering keeps the common case fast without blanket exemption.
