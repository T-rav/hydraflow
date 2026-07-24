---
id: 0378
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:53:43.447771+00:00
status: superseded
corroborations: 1
supersedes: 0364,0365,0366,0367,0368,0369,0370,0371,0372
superseded_by: 0388
---

# Keep make audit out of quality-lite; gate it by touched-path instead

The Makefile deliberately keeps `make audit` (the Principles Audit) separate from `make quality-lite`, which is the pre-push hook's fast common-path target (`.githooks/pre-push` runs `make quality-lite` unconditionally on every push). Folding audit into quality-lite would add ~1–3 min to every push instead of only the rare push touching convention paths.

Example: gate `make audit` behind a path-triggered conditional block (`Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, ADR-0044) instead of merging targets.

**Why:** cost containment for the common case, not a blanket exemption from ever running audit locally.
