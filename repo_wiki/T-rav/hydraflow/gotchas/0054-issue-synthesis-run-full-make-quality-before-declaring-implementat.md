---
id: 0054
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.334787+00:00
status: superseded
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
superseded_by: 0078
---

# Run full `make quality` before declaring implementation complete

Always run the full `make quality` gate — never a file-targeted test subset — before declaring a task done.

Example: `pytest tests/test_foo.py` passes; `make quality` reveals 7 failures in `test_audit_prompts.py` caused by the same change (PR #8460 → hotfix #8463).

**Why:** Targeted runs miss cross-module regressions; cleanup PRs have higher blast radius than their diffs suggest.
