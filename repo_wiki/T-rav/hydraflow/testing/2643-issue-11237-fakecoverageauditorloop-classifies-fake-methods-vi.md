---
id: 2643
topic: testing
source_issue: 11237
source_phase: plan
created_at: 2026-08-15T09:27:56.205892+00:00
status: active
corroborations: 1
---

# FakeCoverageAuditorLoop classifies fake methods via PRManager/PRPort

New public methods on `FakeGitHub` are classified as scaffolding (not untracked fake surface) automatically if they don't appear on `PRManager` or `PRPort`. `_HELPER_PREFIXES` covers only `script_`-prefixed names. Helpers like `set_strict_run_gh()` need no `_FAKE_HELPER_OVERRIDES` entry.

- Re-run `tests/test_fake_coverage_auditor*` and `tests/architecture/test_mockworld_scenario_fake_boundaries.py` after any fake surface change.

**Why:** The auditor's blast radius exceeds the diff — new fake methods can trip architecture tests if classification rules shift.
