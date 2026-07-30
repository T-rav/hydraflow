---
id: 0243
topic: architecture
source_issue: 10748
source_phase: plan
created_at: 2026-07-27T22:35:59.585794+00:00
status: active
corroborations: 1
---

# Scenario tests must stay FakeGitHub-only — no subprocess or gh calls

Escape-ledger scenario tests in `tests/scenarios/test_escape_ledger_scenario.py` must exercise the full tick-to-tick lifecycle using `FakeGitHub` only.

- No `subprocess.run`, no real `gh` invocations.
- A surfaced escape closed by a human confirm via the resolve service should be verified through `FakeGitHub` issue state across ticks.

**Why:** Subprocess-based tests are flaky in CI and couple to a real GitHub CLI auth context that the test harness does not own.
