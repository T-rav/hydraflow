---
id: 4084
topic: patterns
source_issue: 11869
source_phase: plan
created_at: 2026-09-01T05:42:49.576664+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Enforcement ladder order: exempt, regulated-binds, grandfathered

Place new enforcement arms in `_decide_enforcement` after `exempt` and before the grandfathered arm. Fire regulated-class rules only on `EnforcementClass.WEAK`, not `MISSING`.

Example: the OPA-pilot rule checks `binds in {"factory", "both"}` + `Charter.is_regulated` + WEAK class → `blocking`, even when the ADR is grandfathered.

**Why:** Ladder precedence determines which verdict wins; exempt must always win first, and the grandfathered arm must not shadow regulated-class blocking.
