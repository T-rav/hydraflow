---
id: 0463
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:15:19.406653+00:00
status: superseded
corroborations: 1
supersedes: 0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462
superseded_by: 0481
---

# New PR-query helpers must request isDraft like existing ones in pr_manager.py

Every draft-sensitive PR query in `src/pr_manager.py` (lines 706, 1117, 1881, 3505) requests and checks `isDraft` in its `--json` projection; a new helper that omits it (e.g. `find_open_resolving_pr`) treats draft PRs as ready.

Example: add `isDraft` to the JSON projection and skip draft PRs, mirroring `FakeGitHub.find_open_resolving_pr` (`FakePR` already carries a `draft` field).

**Why:** this repo's CI doesn't exclude draft PRs, so a draft can silently satisfy "resolving PR exists" checks it shouldn't.
