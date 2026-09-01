---
id: 1550
topic: gotchas
source_issue: 11937
source_phase: plan
created_at: 2026-09-01T09:28:20.470664+00:00
status: active
corroborations: 1
---

# P10.8 verdict mapping is three-way: blocking FAILs, advisory WARNs

Map P10.8 verdicts three ways in `scripts/hydraflow_audit/checks/p10_tdd.py` (lines 570-593): `d.blocking` → FAIL; `d.status is DecisionStatus.VIOLATED and not d.blocking` → `Status.WARN` carrying `d.reason`; COMPLIANT/EXEMPT → PASS. Waiver is read AFTER the verdict.

ADR-0044's P10.8 row declares conditional cells and ambiguous `feat(...)` "only warn" — a two-way PASS/FAIL collapse discards the advisory reason the engine computes.

**Why:** Collapsing WARN into PASS means `format_terminal` (which skips PASS detail) silently drops the advisory text the standard promises to surface.
