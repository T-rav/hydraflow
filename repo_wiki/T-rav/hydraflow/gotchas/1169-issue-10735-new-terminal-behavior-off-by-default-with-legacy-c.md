---
id: 1169
topic: gotchas
source_issue: 10735
source_phase: plan
created_at: 2026-07-27T20:01:28.594793+00:00
status: active
corroborations: 1
---

# New terminal behavior: off-by-default with legacy cap fallback

Gate new terminal behavior behind a config flag in `src/config.py`, off by default. For `plan_retry`, default the threshold to today's `max_route_backs` so existing deployments see no behavior change. Old ledgers load with empty events — no migration needed.

- P2 test: pre-change ledger JSON loads with empty events; two events survive reload as count 2
- `src/precondition_gate.py` clears the window on READY-stage pass

**Why:** Changing terminal behavior without a default-off flag silently alters convergence for all issues.
