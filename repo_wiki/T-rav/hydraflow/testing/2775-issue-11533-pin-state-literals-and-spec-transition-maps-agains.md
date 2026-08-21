---
id: 2775
topic: testing
source_issue: 11533
source_phase: plan
created_at: 2026-08-21T09:41:01.976105+00:00
status: active
corroborations: 1
---

# Pin state literals and spec transition maps against reintroduction

When deleting states or transitions from a `src/models.py` literal or a spec's transition map, add a regression pin so they cannot silently return.
- `tests/regressions/test_issue_11533.py` asserts the DriverState literal (`src/models.py:1877`) and the rewritten 2026-07-20 spec map contain no DISCOVER/SHAPE, and that ADR-0135 stays Accepted+enforced.
- ADR-0100 ratchet: an "Enforced by" reference must resolve via a non-mutating check (mirror `regression_issue_10038.py`).
**Why:** Specs drift from code silently — the 2026-07-20 spec still described states the state layer had already dropped.
