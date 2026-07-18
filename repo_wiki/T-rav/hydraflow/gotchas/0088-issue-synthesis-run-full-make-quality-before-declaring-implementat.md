---
id: 0088
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:10:32.483951+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Run full `make quality` before declaring implementation complete

Always run the full `make quality` gate — never a file-targeted test subset — before declaring a task done.

Example: `pytest tests/test_foo.py` passes; `make quality` reveals 7 failures in `test_audit_prompts.py` caused by the same change.

**Why:** Targeted runs miss cross-module regressions; cleanup PRs have higher blast radius than their diffs suggest.
