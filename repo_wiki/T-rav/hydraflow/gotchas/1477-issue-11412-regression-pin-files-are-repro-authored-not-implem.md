---
id: 1477
topic: gotchas
source_issue: 11412
source_phase: plan
created_at: 2026-08-18T02:58:42.910251+00:00
status: active
corroborations: 1
---

# Regression pin files are repro-authored, not implementer-authored

`tests/regressions/test_issue_<N>.py` pin files are authored by the repro phase and ship as-is. The implementer runs them to confirm RED→GREEN, adds no helpers that mirror `tests/conftest.py`, and never weakens an assertion to make a test pass. Sibling-class regressions (e.g. `test_diagnostic_infra_classification_11370.py`) must stay GREEN alongside the new pin file.

**Why:** The pin file is the repro contract; weakening it silently erodes the failure class the issue was filed to close.
