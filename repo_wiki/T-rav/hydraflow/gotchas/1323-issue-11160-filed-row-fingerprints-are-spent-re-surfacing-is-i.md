---
id: 1323
topic: gotchas
source_issue: 11160
source_phase: plan
created_at: 2026-08-14T18:34:20.225973+00:00
status: active
corroborations: 1
---

# Filed row fingerprints are spent; re-surfacing is impossible

A filed row's reason-scoped fingerprint is a one-shot budget that can never re-enter `select_findings_to_surface`. Already-filed aging issues stay open forever unless `_reconcile_surfaced_issues` independently runs diagnosis on open surfaced links before computing `answered_surfacings`.

**Why:** Widening the `_auto_diagnose` filter alone does not unstrand already-filed issues — the reconcile entry point is mandatory.
