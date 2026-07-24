---
id: 0452
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:37:14.512699+00:00
status: active
corroborations: 1
supersedes: 0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
---

# Keep make audit out of quality-lite; gate it by touched-path instead

Keep `make audit` (the Principles Audit) out of `make quality-lite`, the pre-push hook's fast common-path target (`.githooks/pre-push` runs `make quality-lite` unconditionally on every push); gate `make audit` behind a path-triggered conditional instead.

Example: trigger on changes to `Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, or ADR-0044, rather than merging the targets.

**Why:** cost containment for the common case — folding audit into quality-lite would add ~1–3 min to every push, not a blanket exemption from ever running audit locally.
