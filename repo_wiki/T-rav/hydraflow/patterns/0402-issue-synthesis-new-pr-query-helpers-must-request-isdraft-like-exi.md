---
id: 0402
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:02:15.935999+00:00
status: active
corroborations: 1
supersedes: 0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# New PR-query helpers must request isDraft like existing ones in pr_manager.py

Every draft-sensitive PR query in `src/pr_manager.py` (lines 706, 1117, 1881, 3505) requests and checks `isDraft` in its `--json` projection; a new helper that omits it (e.g. `find_open_resolving_pr`) treats draft PRs as ready. Example: add `isDraft` to the JSON projection and skip draft PRs, mirroring the check in `FakeGitHub.find_open_resolving_pr` (`FakePR` already carries a `draft` field). **Why:** this repo's CI doesn't exclude draft PRs, so a draft can silently satisfy "resolving PR exists" checks it shouldn't.
