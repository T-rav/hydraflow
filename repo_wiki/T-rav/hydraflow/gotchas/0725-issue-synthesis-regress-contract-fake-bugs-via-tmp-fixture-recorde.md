---
id: 0725
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.825424+00:00
status: superseded
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
superseded_by: 0764
---

# Regress contract-fake bugs via tmp-fixture recorder round-trip

For bugs in cassette-generation logic (e.g. `src/contract_recording.py`'s `record_git`), write the regression test to drive the real recorder against a pristine tmp copy of the fixture and replay the output through the current fake — not just assert on the committed cassette.

Example: `tests/regressions/test_issue_10230.py` must fail red pre-fix with "stdout drift after normalizers ['sha:short']", and skip (not error) when `git` is absent from PATH.

**Why:** Proves the fix works for the next refresh tick's freshly-recorded cassette, not just the one hand-authored cassette committed alongside the fix.
