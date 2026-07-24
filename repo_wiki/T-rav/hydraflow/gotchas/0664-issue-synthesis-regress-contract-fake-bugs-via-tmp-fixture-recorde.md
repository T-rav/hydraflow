---
id: 0664
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.458368+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# Regress contract-fake bugs via tmp-fixture recorder round-trip

For bugs in cassette-generation logic (e.g. `src/contract_recording.py`'s `record_git`), write the regression test to drive the real recorder against a pristine tmp copy of the fixture and replay the output through the current fake — not just assert on the committed cassette.

Example: `tests/regressions/test_issue_10230.py` must fail red pre-fix with "stdout drift after normalizers ['sha:short']", and skip (not error) when `git` is absent from PATH.

**Why:** Proves the fix works for the next refresh tick's freshly-recorded cassette, not just the one hand-authored cassette committed alongside the fix.
