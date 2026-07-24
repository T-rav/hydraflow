---
id: 0393
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.607584+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
superseded_by: 0402
---

# Keep make audit out of quality-lite; gate it by touched-path instead

The Makefile deliberately keeps `make audit` (the Principles Audit) separate from `make quality-lite`, which is the pre-push hook's fast common-path target (`.githooks/pre-push` runs `make quality-lite` unconditionally on every push).

Example: gate `make audit` behind a path-triggered conditional block (`Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, ADR-0044) instead of merging targets.

**Why:** cost containment for the common case — folding audit into quality-lite would add ~1–3 min to every push, not a blanket exemption from ever running audit locally.
