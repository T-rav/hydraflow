---
id: 0481
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:35:28.277869+00:00
status: active
corroborations: 1
supersedes: 0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480
---

# New PR-query helpers must request isDraft like existing ones in pr_manager.py

Every draft-sensitive PR query in `src/pr_manager.py` (lines 706, 1117, 1881, 3505) requests and checks `isDraft` in its `--json` projection; a new helper that omits it (e.g. `find_open_resolving_pr`) treats draft PRs as ready.

Example: add `isDraft` to the JSON projection and skip draft PRs, mirroring `FakeGitHub.find_open_resolving_pr` (`FakePR` already carries a `draft` field).

**Why:** this repo's CI doesn't exclude draft PRs, so a draft can silently satisfy "resolving PR exists" checks it shouldn't.
