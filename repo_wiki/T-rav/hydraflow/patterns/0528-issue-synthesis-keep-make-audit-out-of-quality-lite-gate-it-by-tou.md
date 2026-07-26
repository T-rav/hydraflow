---
id: 0528
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.235429+00:00
status: active
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
---

# Keep make audit out of quality-lite; gate it by touched-path instead

Keep `make audit` (the Principles Audit) out of `make quality-lite`, the pre-push hook's fast common-path target (`.githooks/pre-push` runs `make quality-lite` unconditionally on every push); gate `make audit` behind a path-triggered conditional instead.

Example: trigger on changes to `Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, or ADR-0044, rather than merging the targets.

**Why:** cost containment for the common case — folding audit into quality-lite would add ~1–3 min to every push, not a blanket exemption from ever running audit locally.
