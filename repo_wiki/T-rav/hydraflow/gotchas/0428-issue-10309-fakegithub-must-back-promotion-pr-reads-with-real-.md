---
id: 0428
topic: gotchas
source_issue: 10309
source_phase: plan
created_at: 2026-07-24T04:15:22.309918+00:00
status: superseded
corroborations: 1
superseded_by: 0446
---

# FakeGitHub must back promotion-PR reads with real state, not stubs

`FakeGitHub` (src/mockworld/fakes/fake_github.py) can *cut* an RC branch/PR but its `find_open_promotion_pr`, `list_recent_promotion_prs`, and `list_rc_branches` don't see it again unless `create_rc_branch`/`create_promotion_pr` record state into an explicit promotion-PR number set and rc-branch map. A standard `create_pr` (issue_number>0) must never be returned by `find_open_promotion_pr` — distinguish by explicit ID set, not base-branch/issue heuristics, or `StagingPromotionLoop` can grab a normal agent PR.
**Why:** Silent stub returns make MockWorld-tier promotion scenarios (e.g. `StagingPromotionLoop` cut→find→merge) pass trivially without exercising the real read path.
