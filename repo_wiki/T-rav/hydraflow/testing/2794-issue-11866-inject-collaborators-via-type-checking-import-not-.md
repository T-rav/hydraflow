---
id: 2794
topic: testing
source_issue: 11866
source_phase: plan
created_at: 2026-09-01T03:52:25.540755+00:00
status: active
corroborations: 1
---

# Inject collaborators via TYPE_CHECKING import, not new ports.py Port

When a background loop needs a typed collaborator that isn't a process Port, type it via `TYPE_CHECKING` import and inject it in the constructor. Do not add a new `ports.py` Port.
- Adding a Port pulls in `functional_areas.yml` Port-half coverage and `test_ports.py` fake parity for no functional gain.
- `CharterLoopWorkerLoop` types `CharterLoopRunner` this way per ADR-0029.
**Why:** Ports carry a heavyweight test-coverage tax; a `TYPE_CHECKING`-typed collaborator avoids it entirely.
