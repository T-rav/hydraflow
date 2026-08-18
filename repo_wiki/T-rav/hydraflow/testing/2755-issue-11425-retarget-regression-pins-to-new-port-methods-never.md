---
id: 2755
topic: testing
source_issue: 11425
source_phase: plan
created_at: 2026-08-18T04:29:33.971212+00:00
status: active
corroborations: 1
---

# Retarget regression pins to new Port methods, never delete

When a plan removes a call path a regression pin mocks, retarget the pin to the new Port method — deleting the assertion is not fixing it.
- `tests/regressions/test_issue_11419.py` mocks `_run_gh`; after promotion to `PRPort.list_branch_refs` / `list_branch_commits`, rewrite the mocks against the Port method.
- Keep liveness/counter-pins intact across the retarget.
**Why:** A deleted assertion removes the only witness that the new path still does what the old one did; the pin survives the refactor by changing what it mocks, not by going away.
