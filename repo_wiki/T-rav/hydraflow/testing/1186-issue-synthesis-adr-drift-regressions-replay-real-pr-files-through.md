---
id: 1186
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.878116+00:00
status: active
corroborations: 1
supersedes: 1117
---

# ADR-drift regressions replay real PR files through ADRIndex

Pin ADR citation/drift false-positive fixes by driving real inputs through the production ADRIndex and compute_drift/by_adr entry points (src/adr_drift.py + src/adr_index.py) — never a synthetic mock ADR or a stubbed drift engine.

Example: tests/regressions/test_issue_10384.py, test_issue_10411.py replay actual merged PR file lists through ADRIndex. Pair with a tmp_path-fixture ADR that bare-cites a non-exempt module to prove the auditor still fires generally.

**Why:** A fixture-only or stubbed test can pass while the live ADR/engine regresses or still fires falsely on production diffs, silently reopening the same rollup.
