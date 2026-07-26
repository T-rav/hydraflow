---
id: 0584
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.326209+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# New PR-query helpers must request isDraft like existing ones in pr_manager.py

Every draft-sensitive PR query in `src/pr_manager.py` requests and checks `isDraft` in its `--json` projection; a new helper that omits it (e.g. `find_open_resolving_pr`) treats draft PRs as ready.

Example: add `isDraft` to the JSON projection and skip draft PRs, mirroring `FakeGitHub.find_open_resolving_pr` (`FakePR` already carries a `draft` field).

**Why:** this repo's CI doesn't exclude draft PRs, so a draft can silently satisfy "resolving PR exists" checks it shouldn't.
