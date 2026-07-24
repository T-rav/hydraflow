---
id: 0373
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:53:43.444916+00:00
status: superseded
corroborations: 1
supersedes: 0364,0365,0366,0367,0368,0369,0370,0371,0372
superseded_by: 0388
---

# New PR-query helpers must request isDraft like existing ones in pr_manager.py

Every draft-sensitive PR query in `src/pr_manager.py` (lines 706, 1117, 1881, 3505) requests and checks `isDraft` in its `--json` projection — a new helper that doesn't (e.g. `find_open_resolving_pr`) will treat draft PRs as ready, suppressing dispatch or clearing labels before the author intends.

Example: add `isDraft` to the JSON projection and skip draft PRs; mirror the check in `FakeGitHub.find_open_resolving_pr` (`FakePR` already carries a `draft` field).

**Why:** This repo's CI doesn't exclude draft PRs, so a draft can silently satisfy "resolving PR exists" checks it shouldn't.
