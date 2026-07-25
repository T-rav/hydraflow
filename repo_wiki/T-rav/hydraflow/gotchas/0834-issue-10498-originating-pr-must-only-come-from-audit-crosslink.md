---
id: 0834
topic: gotchas
source_issue: 10498
source_phase: plan
created_at: 2026-07-25T01:51:29.166460+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# originating_pr must only come from audit.crosslink's real PR+merge sha

In `src/escape/detect.py`, a commit body like `Closes #N` names an issue the commit closed, not the PR that introduced the defect. `_origin_pointer` must leave `originating_pr` unset (`None`) and expose the number only as `originating_ref = "#N"`, which still selects the `fixes-chain` attribution method at `low` confidence.

- Only `audit.crosslink` may set `originating_pr`, and only from a genuine `pr_number` + merge sha pair.
- Guard tests: `tests/test_sampled_audit_loop.py`, `tests/test_audit_engine.py:361`, `tests/scenarios/test_sampled_audit_scenario.py:190` must stay green to prove that writer wasn't disturbed.

**Why:** conflating "issue closed by this commit" with "PR that introduced the bug" fabricates false-positive escape rows (issue #10498).
