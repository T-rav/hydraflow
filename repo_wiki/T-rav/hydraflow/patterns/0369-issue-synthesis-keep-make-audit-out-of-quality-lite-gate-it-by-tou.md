---
id: 0369
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:10:17.166907+00:00
status: active
corroborations: 1
supersedes: 0356,0357,0358,0359,0360,0361,0362,0363
---

# Keep make audit out of quality-lite; gate it by touched-path instead

The Makefile deliberately keeps `make audit` (the Principles Audit) separate from `make quality-lite`, which is the pre-push hook's fast common-path target (`.githooks/pre-push` runs `make quality-lite` unconditionally on every push). Folding audit into quality-lite would add ~1–3 min to every push instead of only the rare push touching convention paths.

Example: gate `make audit` behind a path-triggered conditional block (`Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, ADR-0044) instead of merging targets.

**Why:** cost containment for the common case, not a blanket exemption from ever running audit locally.
