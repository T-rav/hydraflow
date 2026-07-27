---
id: 1213
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.922583+00:00
status: superseded
corroborations: 1
supersedes: 1144
superseded_by: 1287
---

# Escape-ledger scenario tests use FakeGitHub + real git repo

Follow tests/scenarios/test_escape_ledger_scenario.py as the template for new escape-ledger scenario tests: real filesystem git repo + FakeGitHub, marked `pytestmark = pytest.mark.scenario_loops`.

Example: verify end-to-end that resolving a row removes it from the aging/unencoded surface even after the dedup store is cleared — not just that the JSONL line was appended.

**Why:** A unit test on resolve_escape alone can't catch that the HITL issue-generation loop still re-files the same finding after dedup-state reset.
