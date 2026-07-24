---
id: 0842
topic: testing
source_issue: 10455
source_phase: plan
created_at: 2026-07-24T12:32:23.750703+00:00
status: active
corroborations: 1
---

# Pure _SHARED_INFRA_MODULES edits need only unit coverage, not MockWorld/e2e

Per `docs/standards/testing/README.md`'s three-layer pyramid, a change confined to adding string literals to `_SHARED_INFRA_MODULES` in `src/adr_drift.py` (no `_citation_drifts`/resolver/config edits, no phase-crossing behavior, no new loop/runner, no Ports touched) only needs a hermetic unit regression test — skip MockWorld scenario and sandbox e2e, and skip the ADR-0049 kill-switch. **Why:** those layers exist to catch loop-integration and orchestrator wiring bugs that a pure allowlist-data change cannot introduce.
