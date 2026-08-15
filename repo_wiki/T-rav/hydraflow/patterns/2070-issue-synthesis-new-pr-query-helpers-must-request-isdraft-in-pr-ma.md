---
id: 2070
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T23:28:15.960288+00:00
status: superseded
corroborations: 1
supersedes: 1954
superseded_by: 2186
---

# New PR-query helpers must request isDraft in pr_manager.py

Draft-sensitive PR-query helpers in `src/pr_manager.py` must include `isDraft` in their `--json` projection and skip draft PRs.

Example: Existing helpers at lines 706, 1117, 1881, 3505 all request and check `isDraft`; `find_open_resolving_pr` must mirror this. `FakeGitHub.find_open_resolving_pr` already carries a `draft` field on `FakePR`.

**Why:** This repo's CI doesn't exclude draft PRs, so a draft can silently satisfy "resolving PR exists" checks it shouldn't.
