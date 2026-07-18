---
id: 0122
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.465894+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Run full `make quality` before declaring implementation complete

Always run the full `make quality` gate — never a file-targeted test subset — before declaring a task done.

Example: `pytest tests/test_foo.py` passes; `make quality` reveals 7 failures in `test_audit_prompts.py` caused by the same change (PR #8460 → hotfix #8463).

**Why:** Targeted runs miss cross-module regressions; cleanup PRs have higher blast radius than their diffs suggest.
