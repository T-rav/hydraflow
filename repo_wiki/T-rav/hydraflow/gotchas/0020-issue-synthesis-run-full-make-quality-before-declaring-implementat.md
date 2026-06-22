---
id: 0020
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.694480+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Run full `make quality` before declaring implementation complete

Always run the full `make quality` gate — never a file-targeted test subset — before declaring a task done.

Example: `pytest tests/test_foo.py` passes; `make quality` reveals 7 failures in `test_audit_prompts.py` caused by the same change (PR #8460 → hotfix #8463).

**Why:** Targeted runs miss cross-module regressions; cleanup PRs have higher blast radius than their diffs suggest.
