---
id: 0361
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:01:25.884933+00:00
status: active
corroborations: 1
supersedes: 0350,0350,0351,0352,0353,0354,0355
---

# Keep make audit out of quality-lite; gate it by touched-path instead

The Makefile deliberately keeps `make audit` (the Principles Audit) separate from `make quality-lite`, which is the pre-push hook's fast common-path target (`.githooks/pre-push` runs `make quality-lite` unconditionally on every push). Folding audit into quality-lite would add ~1–3 min to every push instead of only the rare push touching convention paths (`Makefile`, `.githooks/**`, `scripts/hydraflow_audit/**`, ADR-0044). Gate `make audit` behind a path-triggered conditional block instead of merging targets.

**Why:** This is the concrete rule behind memory `feedback_make_audit_separate_from_quality` — cost containment for the common case, not a blanket exemption from ever running audit locally.
