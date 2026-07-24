---
id: 0619
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.452706+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# FakeGitHub must back promotion-PR reads with real state, not stubs

`FakeGitHub` (src/mockworld/fakes/fake_github.py) can cut an RC branch/PR but its `find_open_promotion_pr`, `list_recent_promotion_prs`, and `list_rc_branches` don't see it again unless `create_rc_branch`/`create_promotion_pr` record state into an explicit promotion-PR number set and rc-branch map.

Example: a standard `create_pr` (issue_number>0) must never be returned by `find_open_promotion_pr` — distinguish by explicit ID set, not base-branch/issue heuristics, or `StagingPromotionLoop` can grab a normal agent PR.

**Why:** Silent stub returns make MockWorld-tier promotion scenarios (e.g. `StagingPromotionLoop` cut→find→merge) pass trivially without exercising the real read path.
