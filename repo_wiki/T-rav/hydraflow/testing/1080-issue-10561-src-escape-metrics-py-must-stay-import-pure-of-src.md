---
id: 1080
topic: testing
source_issue: 10561
source_phase: plan
created_at: 2026-07-25T23:57:26.301216+00:00
status: superseded
corroborations: 1
superseded_by: 1085
---

# src/escape/metrics.py must stay import-pure of src/escape/ledger.py

`escape/metrics.py` may never import from `escape/ledger.py` — the dependency is one-directional, ledger imports metrics helpers (`latest_by_escape`, `latest_by_id`), not the reverse. When adding new collapse/aggregation logic for the escape ledger, put it in `metrics.py` even if it feels ledger-specific.

**Why:** keeps `metrics` reusable as a pure computation module (used by loop reports, HITL surface, `vitals.observe`, `sampled_audit_loop`) without pulling in ledger's file I/O.
