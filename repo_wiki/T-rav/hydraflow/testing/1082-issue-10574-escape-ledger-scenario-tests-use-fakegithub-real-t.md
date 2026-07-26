---
id: 1082
topic: testing
source_issue: 10574
source_phase: plan
created_at: 2026-07-26T00:21:42.291392+00:00
status: superseded
corroborations: 1
superseded_by: 1085
---

# Escape-ledger scenario tests use FakeGitHub + real tiny git repo, tagged scenario_loops

Follow `tests/scenarios/test_escape_ledger_scenario.py` as the template for new escape-ledger scenario tests (e.g. `test_escape_resolution_scenario.py`): real filesystem git repo + `FakeGitHub`, marked `pytestmark = pytest.mark.scenario_loops`, verifying end-to-end that resolving a row removes it from the aging/unencoded surface even after the dedup store is cleared — not just that the JSONL line was appended.

**Why:** a unit test on `resolve_escape` alone can't catch that the HITL issue-generation loop still re-files the same finding after dedup-state reset.
