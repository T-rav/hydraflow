---
id: 1504
topic: gotchas
source_issue: 11424
source_phase: review
created_at: 2026-08-18T09:01:27.985897+00:00
status: active
corroborations: 1
---

# Honor regression pin paths from plan acceptance criteria

When a plan specifies a regression pin path like `tests/regressions/test_issue_11424.py` as an acceptance criterion ("the contract"), that file must exist in the PR diff. Do not silently drop acceptance criteria even if another PR's fix happens to cover the same contract.

**Why:** Missing regression pins mean future regressions of the same bug go undetected, and the acceptance contract is broken even if behavior is currently correct.
