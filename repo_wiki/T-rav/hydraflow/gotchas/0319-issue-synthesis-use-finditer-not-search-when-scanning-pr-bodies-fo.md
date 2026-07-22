---
id: 0319
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:38:34.193880+00:00
status: active
corroborations: 1
supersedes: 0310,0310,0311,0311,0312,0312,0313,0314,0315,0316
---

# Use finditer, not search, when scanning PR bodies for Fixes links

`find_open_resolving_pr` in `src/pr_manager.py` (line ~2318) used `fixes_re.search()`, which only checks the first match — an epic PR body with multiple `Fixes #`/`Closes #`/`Resolves #` links would miss the target issue if it wasn't the leftmost one.

Example: switch to `fixes_re.finditer()` and check all matches against the target issue number.

**Why:** Under-detection here means a genuinely resolving PR gets treated as absent, causing incorrect escalation/dispatch decisions for issues resolved by multi-issue PRs.
