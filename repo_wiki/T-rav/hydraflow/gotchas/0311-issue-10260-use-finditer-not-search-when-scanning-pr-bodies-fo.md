---
id: 0311
topic: gotchas
source_issue: 10260
source_phase: review
created_at: 2026-07-22T11:54:54.586684+00:00
status: active
corroborations: 1
---

# Use finditer, not search, when scanning PR bodies for Fixes/Closes links

`find_open_resolving_pr` in `src/pr_manager.py` (line ~2318) used `fixes_re.search()`, which only checks the first match — an epic PR body with multiple `Fixes #`/`Closes #`/`Resolves #` links would miss the target issue if it wasn't the leftmost one. Switch to `fixes_re.finditer()` and check all matches against the target issue number.

**Why:** Under-detection here means a genuinely resolving PR gets treated as absent, causing incorrect escalation/dispatch decisions for issues resolved by multi-issue PRs.
