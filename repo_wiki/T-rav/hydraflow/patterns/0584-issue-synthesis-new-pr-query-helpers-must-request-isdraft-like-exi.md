---
id: 0584
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:31:18.150409+00:00
status: active
corroborations: 1
supersedes: 0550,0577,0578,0579
---

# New PR-query helpers must request isDraft like existing ones in pr_manager.py

New draft-sensitive PR-query helpers in `src/pr_manager.py` must include `isDraft` in their `--json` projection and skip draft PRs.

Example: Existing helpers at lines 706, 1117, 1881, 3505 all request and check `isDraft`; `find_open_resolving_pr` must mirror this. `FakeGitHub.find_open_resolving_pr` already carries a `draft` field on `FakePR`.

**Why:** This repo's CI doesn't exclude draft PRs, so a draft can silently satisfy "resolving PR exists" checks it shouldn't.
