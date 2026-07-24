---
id: 0520
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.790075+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# FakeGitHub must back promotion-PR reads with real state, not stubs

`FakeGitHub` (src/mockworld/fakes/fake_github.py) can cut an RC branch/PR but its `find_open_promotion_pr`, `list_recent_promotion_prs`, and `list_rc_branches` don't see it again unless `create_rc_branch`/`create_promotion_pr` record state into an explicit promotion-PR number set and rc-branch map.

Example: a standard `create_pr` (issue_number>0) must never be returned by `find_open_promotion_pr` — distinguish by explicit ID set, not base-branch/issue heuristics, or `StagingPromotionLoop` can grab a normal agent PR.

**Why:** Silent stub returns make MockWorld-tier promotion scenarios (e.g. `StagingPromotionLoop` cut→find→merge) pass trivially without exercising the real read path.
