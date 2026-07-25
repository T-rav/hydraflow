---
id: 1013
topic: testing
source_issue: 10531
source_phase: plan
created_at: 2026-07-25T09:52:15.451018+00:00
status: active
corroborations: 1
---

# ADR-drift regression tests replay real merged PR file lists through the production ADRIndex

Repo convention (see `tests/regressions/test_issue_9176.py`, `test_issue_10455_review_path_shared_infra.py`, and `test_issue_10531.py`): pin a false-positive fix by driving the *actual* merged file list from the offending PR (e.g. PR #10519's `src/implement_phase.py`, `src/phase_utils.py`, plus its test files) through the real `docs/adr` tree via the production `ADRIndex` and drift/`by_adr` entry points — no stubs, no monkeypatching the drift engine. Pair with a `tmp_path`-fixture ADR that bare-cites a non-exempt module to prove the auditor still fires generally (not disabled wholesale), and a self-retiring premise guard that skips if the ADR is absent, non-live, or no longer cites the module. **Why:** stubbed drift tests can pass while the real engine still fires on production diffs — the point is to catch that gap before merge.
