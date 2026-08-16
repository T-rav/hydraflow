---
id: 2658
topic: testing
source_issue: 11281
source_phase: plan
created_at: 2026-08-16T01:24:32.227599+00:00
status: active
corroborations: 1
---

# Self-retiring regression pins live in tests/regressions/test_issue_NNNN.py

New regression pins go in `tests/regressions/test_issue_<N>.py` following the self-retiring convention. These test real code paths (not mocks), asserting the fix's invariants.

Example: `tests/regressions/test_issue_11281.py` asserts both GC gates recognize the auto-agent namespace — pattern matches, prefix tuple includes it.

Run full `make quality` — `branch_gc_scan` is shared by loop + scenario + regression pins, so file-targeted test subsets are insufficient.

**Why:** The self-retiring convention prevents accumulation of stale pins while ensuring the fix's dual-gate invariant is permanently checked. Full quality runs catch cross-module breakage that subset runs miss.
