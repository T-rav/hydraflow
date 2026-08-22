---
id: 0423
topic: architecture
source_issue: 11541
source_phase: plan
created_at: 2026-08-22T00:00:10.177882+00:00
status: active
corroborations: 1
---

# P0 stop-the-line gate forbids stubbing upstream modules

Before implementing a phase that depends on unbuilt infrastructure, verify each upstream module exists on the base branch. If any is absent, stop, comment the missing set on the issue, and re-park.

- #11541 depends on `src/worker_catalog.py`, `src/fable_director.py`, `src/director_broker.py`, `src/director_checkpoint.py`, `src/issue_driver.py`, and gateway v2 resolve-and-mint in `src/hydraflow_gateway/models.py`.
- Stubbing these would create a second, weaker authority — explicitly out of scope.

**Why:** Building against stubs silently replaces the real gateway/broker safety boundary with a fake, which no production path enforces.
