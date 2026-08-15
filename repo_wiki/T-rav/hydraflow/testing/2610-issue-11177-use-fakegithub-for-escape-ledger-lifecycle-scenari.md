---
id: 2610
topic: testing
source_issue: 11177
source_phase: plan
created_at: 2026-08-14T22:44:18.538098+00:00
status: active
corroborations: 1
---

# Use FakeGitHub for escape ledger lifecycle scenarios

For `src/escape/*` lifecycle scenario tests, use `FakeGitHub` instead of `subprocess` or `gh` CLI commands. `tests/scenarios/test_escape_ledger_scenario.py` uses this mock to verify HITL issue filing and closing across multiple ticks.

**Why:** It prevents flaky tests and allows deterministic verification of multi-tick ledger states (e.g., not re-filing closed issues) without external API dependencies.
