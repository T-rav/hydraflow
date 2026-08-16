---
id: 1461
topic: gotchas
source_issue: 11344
source_phase: plan
created_at: 2026-08-16T13:29:50.590341+00:00
status: active
corroborations: 1
---

# FakeIssueFetcher resolves PR→issue by issue_number, not pr.branch

Rule: `FakeIssueFetcher.fetch_reviewable_prs` pairs PRs to issues via `FakeGitHub`'s `issue_number` bookkeeping. It never reads `pr.branch`, so no MockWorld scenario on this Fake can catch branch-resolution regressions.

- The only covering route is `tests/scenarios/test_review_loop_auto_agent_pr_discovery_scenario.py`, which builds the real orchestrator and fakes only `run_subprocess`.
- `tests/regressions/test_issue_11344.py` pins this gap as documented.

**Why:** Authors building MockWorld scenarios on `FakeIssueFetcher` will silently miss branch-resolution bugs if they assume the Fake models production's branch-derived lookup.
