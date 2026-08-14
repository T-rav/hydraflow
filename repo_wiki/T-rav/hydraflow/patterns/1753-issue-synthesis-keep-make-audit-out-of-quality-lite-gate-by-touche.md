---
id: 1753
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:03.641798+00:00
status: active
corroborations: 1
supersedes: 1657
---

# Keep make audit out of quality-lite; gate by touched-path

Keep `make audit` (the Principles Audit) out of `make quality-lite` (the pre-push hook's fast common-path target); gate `make audit` behind a path-triggered conditional instead.

Example: Trigger on changes to `Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, or ADR-0044.

**Why:** Folding audit into quality-lite would add ~1–3 min to every push; this is cost containment, not a blanket exemption from running audit locally.
