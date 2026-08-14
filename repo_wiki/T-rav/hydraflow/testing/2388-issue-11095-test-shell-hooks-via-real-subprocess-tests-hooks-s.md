---
id: 2388
topic: testing
source_issue: 11095
source_phase: plan
created_at: 2026-08-14T08:32:23.164125+00:00
status: active
corroborations: 1
---

# Test shell hooks via real subprocess; tests/hooks/*.sh are not in make quality

Shell hooks under `tests/hooks/*.sh` are excluded from `make quality`, so hook e2e tests must pipe payloads through the real bash wrapper via `subprocess` inside pytest.

Example: `tests/regressions/test_issue_11095.py` invokes `.claude/hooks/hf.no-stop-with-pending-verification.sh` as a subprocess with stdin JSON and asserts on exit code and stderr.

**Why:** If the test only imports the Python module, the bash wrapper layer (env var parsing, exit-code forwarding) is never exercised and breakages go undetected.
