---
id: 0614
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.238047+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Regress contract-fake bugs via tmp-fixture recorder round-trip

For bugs in cassette-generation logic (e.g. `src/contract_recording.py`'s `record_git`), write the regression test to drive the real recorder against a pristine tmp copy of the fixture and replay the output through the current fake — not just assert on the committed cassette.

Example: `tests/regressions/test_issue_10230.py` must fail red pre-fix with "stdout drift after normalizers ['sha:short']", and skip (not error) when `git` is absent from PATH.

**Why:** Proves the fix works for the next refresh tick's freshly-recorded cassette, not just the one hand-authored cassette committed alongside the fix.
