---
id: 2745
topic: testing
source_issue: 11419
source_phase: plan
created_at: 2026-08-18T03:36:18.966929+00:00
status: active
corroborations: 1
---

# MockWorld scenarios: _make_loop_deps direct instantiation, fakes only

New behavioural scenarios live in `tests/scenarios/` and use `_make_loop_deps`-style direct instantiation with fakes only — no subprocess or real `gh`. Name the file for the behaviour, not the issue number (e.g. `test_report_issue_verification_scenario.py`). Mirror the L19 block of `tests/scenarios/test_caretaker_loops_part2.py`.

Assert original-body preservation, not just URL presence, to prove the read projection and write path together.

**Why:** Subprocess-based tests cannot exercise `FakeGitHub` state transitions; direct-instantiation scenarios are the fidelity gate that catches writer/projection mismatches before they ship.
