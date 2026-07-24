---
id: 0472
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.396356+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
---

# FakeGitHub must back promotion-PR reads with real state, not stubs

`FakeGitHub` (src/mockworld/fakes/fake_github.py) can *cut* an RC branch/PR but its `find_open_promotion_pr`, `list_recent_promotion_prs`, and `list_rc_branches` don't see it again unless `create_rc_branch`/`create_promotion_pr` record state into an explicit promotion-PR number set and rc-branch map. A standard `create_pr` (issue_number>0) must never be returned by `find_open_promotion_pr` — distinguish by explicit ID set, not base-branch/issue heuristics, or `StagingPromotionLoop` can grab a normal agent PR.

**Why:** Silent stub returns make MockWorld-tier promotion scenarios (e.g. `StagingPromotionLoop` cut→find→merge) pass trivially without exercising the real read path.
