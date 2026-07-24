---
id: 0407
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:02:15.941808+00:00
status: superseded
corroborations: 1
supersedes: 0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
superseded_by: 0416
---

# Keep make audit out of quality-lite; gate it by touched-path instead

Keep `make audit` (the Principles Audit) out of `make quality-lite`, the pre-push hook's fast common-path target (`.githooks/pre-push` runs `make quality-lite` unconditionally on every push); gate `make audit` behind a path-triggered conditional instead. Example: trigger on changes to `Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, or ADR-0044, rather than merging the targets. **Why:** cost containment for the common case — folding audit into quality-lite would add ~1–3 min to every push, not a blanket exemption from ever running audit locally.
