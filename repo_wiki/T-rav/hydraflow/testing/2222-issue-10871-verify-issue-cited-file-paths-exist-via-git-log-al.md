---
id: 2222
topic: testing
source_issue: 10871
source_phase: review
created_at: 2026-07-31T16:47:39.085961+00:00
status: stale
corroborations: 1
stale_reason: source issue #10871 closed
---

# Verify issue-cited file paths exist via git log --all

Before acting on an issue that cites a specific file as motivating evidence, run `git log --all -- <path>` to confirm the file exists in repo history. Issue premises can be fictional or stale.

- Issue #10871 cited `tests/regressions/test_issue_10859.py` as the motivating cross-module importer; `git log --all` confirmed it never existed. The fix was still valid as general hygiene per wiki 0279/0281.

**Why:** Fictional premises in issue bodies propagate into the wiki and downstream plans, causing scope confusion in future iterations.
