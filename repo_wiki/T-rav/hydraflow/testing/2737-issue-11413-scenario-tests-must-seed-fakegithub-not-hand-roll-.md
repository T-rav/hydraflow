---
id: 2737
topic: testing
source_issue: 11413
source_phase: plan
created_at: 2026-08-18T03:10:14.007973+00:00
status: active
corroborations: 1
---

# Scenario tests must seed FakeGitHub, not hand-roll MagicMock._run_gh

Scenario tests in `tests/scenarios/` must seed and assert against `FakeGitHub` state, not override `_run_gh` with a hand-rolled `MagicMock`.

- `TestL23cBranchGC` used `MagicMock._run_gh`, bypassing `FakeGitHub`'s fail-loud dispatch — the branch-GC gap stayed invisible.
- Migrate to `add_branch`/`add_pr`/`add_issue`/`close_issue` seeders and assert against fake state (e.g. branch absent from ref listing).
- If a case genuinely cannot be expressed through the fake, keep it on the mock with a one-line stated reason.

**Why:** A hand-rolled mock short-circuits the fake's fail-loud contracts, recreating the blind spot the fake exists to prevent.
