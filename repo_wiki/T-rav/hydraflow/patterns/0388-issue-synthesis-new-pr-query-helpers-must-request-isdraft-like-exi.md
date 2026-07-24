---
id: 0388
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.603145+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
superseded_by: 0402
---

# New PR-query helpers must request isDraft like existing ones in pr_manager.py

Every draft-sensitive PR query in `src/pr_manager.py` (lines 706, 1117, 1881, 3505) requests and checks `isDraft` in its `--json` projection. A new helper that doesn't (e.g. `find_open_resolving_pr`) will treat draft PRs as ready, suppressing dispatch or clearing labels before the author intends.

Example: add `isDraft` to the JSON projection and skip draft PRs; mirror the check in `FakeGitHub.find_open_resolving_pr` (`FakePR` already carries a `draft` field).

**Why:** This repo's CI doesn't exclude draft PRs, so a draft can silently satisfy "resolving PR exists" checks it shouldn't.
