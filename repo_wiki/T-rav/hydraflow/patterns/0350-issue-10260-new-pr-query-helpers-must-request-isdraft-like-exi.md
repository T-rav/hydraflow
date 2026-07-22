---
id: 0350
topic: patterns
source_issue: 10260
source_phase: review
created_at: 2026-07-22T11:54:54.586693+00:00
status: superseded
corroborations: 1
superseded_by: 0356
---

# New PR-query helpers must request isDraft like existing ones in pr_manager.py

Every draft-sensitive PR query in `src/pr_manager.py` (lines 706, 1117, 1881, 3505) requests and checks `isDraft` in its `--json` projection — a new helper that doesn't (e.g. `find_open_resolving_pr`) will treat draft PRs as ready, suppressing dispatch or clearing labels before the author intends. Add `isDraft` to the JSON projection and skip draft PRs; mirror the check in `FakeGitHub.find_open_resolving_pr` (`FakePR` already carries a `draft` field).

**Why:** This repo's CI doesn't exclude draft PRs, so a draft can silently satisfy "resolving PR exists" checks it shouldn't.
