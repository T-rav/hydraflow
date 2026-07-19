---
id: 0190
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.153877+00:00
status: superseded
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
superseded_by: 0214
---

# Run full `make quality` before declaring implementation complete

Always run the full `make quality` gate — never a file-targeted test subset — before declaring a task done.

Example: `pytest tests/test_foo.py` passes; `make quality` reveals 7 failures in `test_audit_prompts.py` caused by the same change.

**Why:** Targeted runs miss cross-module regressions; cleanup PRs have higher blast radius than their diffs suggest.
