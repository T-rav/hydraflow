---
id: 1326
topic: gotchas
source_issue: 11161
source_phase: plan
created_at: 2026-08-14T18:36:34.319392+00:00
status: active
corroborations: 1
---

# RESOLVED_ENCODED closes aging and low-confidence predicates in one tick

A single `RESOLVED_ENCODED` row with `encoded_as="regression-test"` at `attribution_confidence="high"` satisfies both the aging answered-predicate in `_surfacing_answered` and the low-confidence predicate.

- One resolution tick closes both the current issue's aging link and a stranded pre-ADR-0115 sibling (e.g. #10724).
- No manual `make escape-resolve` needed — `_reconcile_surfaced_issues` handles it on the next tick.

**Why:** Splitting predicate closures across ticks leaves orphaned HITL issues that require manual intervention.
