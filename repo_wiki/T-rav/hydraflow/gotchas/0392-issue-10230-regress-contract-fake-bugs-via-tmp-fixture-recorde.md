---
id: 0392
topic: gotchas
source_issue: 10230
source_phase: plan
created_at: 2026-07-22T18:13:39.968099+00:00
status: active
corroborations: 1
---

# Regress contract-fake bugs via tmp-fixture recorder round-trip

For bugs in cassette-generation logic (e.g. `src/contract_recording.py`'s `record_git`), write the regression test to drive the real recorder against a **pristine tmp copy** of the fixture and replay the output through the current fake — not just assert on the committed cassette. `tests/regressions/test_issue_10230.py` follows this shape: it must fail red pre-fix with `"stdout drift after normalizers ['sha:short']"`, and skip (not error) when `git` is absent from PATH.

**Why:** proves the fix works for the *next* refresh tick's freshly-recorded cassette, not just the one hand-authored cassette committed alongside the fix.
