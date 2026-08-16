---
id: 2702
topic: testing
source_issue: 11329
source_phase: plan
created_at: 2026-08-16T09:40:01.182601+00:00
status: active
corroborations: 1
---

# MockWorld cannot observe agent CLI argv shape

Do not add MockWorld scenarios to assert agent spawn flag shape (`bypassPermissions` vs `acceptEdits`/`--allowedTools`).

- MockWorld fakes stub the agent spawn, so CLI argv is not observable.
- Enforcement is via unit tests (`tests/test_reviewer.py`, `tests/test_acceptance_criteria.py`) and `tests/regressions/` pins, per the #11320/#11322 pattern.
- Sandbox e2e likewise cannot see argv.

**Why:** A MockWorld e2e test would pass regardless of whether the restricted kwarg is threaded, giving false confidence on the ADR-0092 hardening.
