---
id: 0515
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.786163+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Regress contract-fake bugs via tmp-fixture recorder round-trip

For bugs in cassette-generation logic (e.g. `src/contract_recording.py`'s `record_git`), write the regression test to drive the real recorder against a pristine tmp copy of the fixture and replay the output through the current fake — not just assert on the committed cassette.

Example: `tests/regressions/test_issue_10230.py` must fail red pre-fix with "stdout drift after normalizers ['sha:short']", and skip (not error) when `git` is absent from PATH.

**Why:** Proves the fix works for the next refresh tick's freshly-recorded cassette, not just the one hand-authored cassette committed alongside the fix.
