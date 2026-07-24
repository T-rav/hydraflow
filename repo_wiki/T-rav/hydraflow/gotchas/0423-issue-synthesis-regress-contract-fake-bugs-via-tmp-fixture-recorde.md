---
id: 0423
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.296074+00:00
status: active
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# Regress contract-fake bugs via tmp-fixture recorder round-trip

For bugs in cassette-generation logic (e.g. `src/contract_recording.py`'s `record_git`), write the regression test to drive the real recorder against a **pristine tmp copy** of the fixture and replay the output through the current fake — not just assert on the committed cassette. `tests/regressions/test_issue_10230.py` follows this shape: it must fail red pre-fix with `"stdout drift after normalizers ['sha:short']"`, and skip (not error) when `git` is absent from PATH.

**Why:** proves the fix works for the *next* refresh tick's freshly-recorded cassette, not just the one hand-authored cassette committed alongside the fix.
