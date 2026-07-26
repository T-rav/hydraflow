---
id: 0499
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:10:56.099430+00:00
status: active
corroborations: 1
supersedes: 0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491,0492,0493,0494,0495,0496,0497,0498
---

# New PR-query helpers must request isDraft like existing ones in pr_manager.py

Every draft-sensitive PR query in `src/pr_manager.py` (lines 706, 1117, 1881, 3505) requests and checks `isDraft` in its `--json` projection; a new helper that omits it (e.g. `find_open_resolving_pr`) treats draft PRs as ready.

Example: add `isDraft` to the JSON projection and skip draft PRs, mirroring `FakeGitHub.find_open_resolving_pr` (`FakePR` already carries a `draft` field).

**Why:** this repo's CI doesn't exclude draft PRs, so a draft can silently satisfy "resolving PR exists" checks it shouldn't.
