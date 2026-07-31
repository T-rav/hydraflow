---
id: 1756
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:20:59.044865+00:00
status: active
corroborations: 1
supersedes: 1662
---

# ADR-drift regressions replay real PR files through ADRIndex

Pin ADR citation/drift false-positive fixes by driving real inputs through the production ADRIndex and compute_drift/by_adr entry points (src/adr_drift.py + src/adr_index.py) — never a synthetic mock ADR or a stubbed drift engine.

Example: tests/regressions/test_issue_10384.py replays actual merged PR file lists through ADRIndex. See also: testing — Test drift-suppression with synthetic ADR fixtures.

**Why:** A fixture-only or stubbed test can pass while the live ADR/engine regresses or still fires falsely on production diffs.
