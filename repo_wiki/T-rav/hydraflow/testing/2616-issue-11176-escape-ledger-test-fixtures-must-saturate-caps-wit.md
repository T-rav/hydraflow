---
id: 2616
topic: testing
source_issue: 11176
source_phase: review
created_at: 2026-08-15T01:02:21.454149+00:00
status: active
corroborations: 1
---

# Escape ledger test fixtures must saturate caps with mixed reasons

Build test fixtures at N == cap and N == cap+k with mixed low-confidence + aging reasons across unit and MockWorld layers.

The shipped #11176 fixtures — `tests/regressions/test_issue_11176.py` (4 findings), `TestMaxDiagnosesPerTick` (5 same-reason findings), and the MockWorld scenario (4 findings) — all sit under both `escape_ledger_max_diagnoses_per_tick` (default 25) and `escape_ledger_max_issues_per_tick` (default 3).

**Why:** Starvation manifests only when one reason category fills the cap; small or single-reason fixtures are structurally incapable of catching the ordering bias.
