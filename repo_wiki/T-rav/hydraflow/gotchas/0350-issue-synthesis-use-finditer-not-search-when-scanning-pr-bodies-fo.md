---
id: 0350
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:02:32.377750+00:00
status: superseded
corroborations: 1
supersedes: 0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347
superseded_by: 0370
---

# Use finditer, not search, when scanning PR bodies for Fixes links

`find_open_resolving_pr` in `src/pr_manager.py` (line ~2318) used `fixes_re.search()`, which only checks the first match — an epic PR body with multiple `Fixes #`/`Closes #`/`Resolves #` links would miss the target issue if it wasn't the leftmost one.

Example: switch to `fixes_re.finditer()` and check all matches against the target issue number.

**Why:** Under-detection here means a genuinely resolving PR gets treated as absent, causing incorrect escalation/dispatch decisions for issues resolved by multi-issue PRs.
