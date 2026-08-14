---
id: 2478
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.135450+00:00
status: active
corroborations: 1
supersedes: 2288
---

# escape/metrics.py must stay import-pure of escape/ledger.py

`escape/metrics.py` may never import from `escape/ledger.py` — the dependency is one-directional (ledger imports metrics helpers like `latest_by_escape`, `latest_by_id`, not the reverse).

Example: when adding new collapse/aggregation logic for the escape ledger, put it in `metrics.py` even if it feels ledger-specific.

**Why:** Keeps metrics reusable as a pure computation module (used by loop reports, HITL surface, `vitals.observe`, `sampled_audit_loop`) without pulling in ledger's file I/O.
