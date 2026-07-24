---
id: 0496
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.771485+00:00
status: superseded
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
superseded_by: 0545
---

# Use finditer, not search, when scanning PR bodies for Fixes links

`find_open_resolving_pr` in `src/pr_manager.py` (line ~2318) used `fixes_re.search()`, which only checks the first match — an epic PR body with multiple `Fixes #`/`Closes #`/`Resolves #` links would miss the target issue if it wasn't the leftmost one.

Example: switch to `fixes_re.finditer()` and check all matches against the target issue number.

**Why:** Under-detection here means a genuinely resolving PR gets treated as absent, causing incorrect escalation/dispatch decisions for issues resolved by multi-issue PRs.
