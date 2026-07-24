---
id: 0571
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.213184+00:00
status: superseded
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
superseded_by: 0593
---

# FakeGitHub must back promotion-PR reads with real state, not stubs

`FakeGitHub` (src/mockworld/fakes/fake_github.py) can cut an RC branch/PR but its `find_open_promotion_pr`, `list_recent_promotion_prs`, and `list_rc_branches` don't see it again unless `create_rc_branch`/`create_promotion_pr` record state into an explicit promotion-PR number set and rc-branch map.

Example: a standard `create_pr` (issue_number>0) must never be returned by `find_open_promotion_pr` — distinguish by explicit ID set, not base-branch/issue heuristics, or `StagingPromotionLoop` can grab a normal agent PR.

**Why:** Silent stub returns make MockWorld-tier promotion scenarios (e.g. `StagingPromotionLoop` cut→find→merge) pass trivially without exercising the real read path.
