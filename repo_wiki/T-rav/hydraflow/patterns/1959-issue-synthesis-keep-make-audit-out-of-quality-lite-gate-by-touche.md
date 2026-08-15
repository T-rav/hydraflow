---
id: 1959
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T18:39:31.624499+00:00
status: superseded
corroborations: 1
supersedes: 1851
superseded_by: 2075
---

# Keep make audit out of quality-lite; gate by touched-path

Keep `make audit` (the Principles Audit) out of `make quality-lite` (the pre-push hook's fast common-path target); gate `make audit` behind a path-triggered conditional instead.

Example: Trigger on changes to `Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, or ADR-0044.

**Why:** Folding audit into quality-lite would add ~1–3 min to every push; this is cost containment, not a blanket exemption from running audit locally.
