---
id: 0329
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T15:33:18.679033+00:00
status: superseded
corroborations: 1
supersedes: 0317,0318,0319,0320,0321,0322,0323,0324,0325,0326
superseded_by: 0337
---

# Use finditer, not search, when scanning PR bodies for Fixes links

`find_open_resolving_pr` in `src/pr_manager.py` (line ~2318) used `fixes_re.search()`, which only checks the first match — an epic PR body with multiple `Fixes #`/`Closes #`/`Resolves #` links would miss the target issue if it wasn't the leftmost one.

Example: switch to `fixes_re.finditer()` and check all matches against the target issue number.

**Why:** Under-detection here means a genuinely resolving PR gets treated as absent, causing incorrect escalation/dispatch decisions for issues resolved by multi-issue PRs.
