---
id: 0504
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:10:56.103061+00:00
status: superseded
corroborations: 1
supersedes: 0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491,0492,0493,0494,0495,0496,0497,0498
superseded_by: 0523
---

# Keep make audit out of quality-lite; gate it by touched-path instead

Keep `make audit` (the Principles Audit) out of `make quality-lite`, the pre-push hook's fast common-path target (`.githooks/pre-push` runs `make quality-lite` unconditionally on every push); gate `make audit` behind a path-triggered conditional instead.

Example: trigger on changes to `Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, or ADR-0044, rather than merging the targets.

**Why:** cost containment for the common case — folding audit into quality-lite would add ~1–3 min to every push, not a blanket exemption from ever running audit locally.
