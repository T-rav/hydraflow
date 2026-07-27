---
id: 1270
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.303747+00:00
status: active
corroborations: 1
supersedes: 1196
---

# Pure _SHARED_INFRA_MODULES edits need only unit coverage

Per docs/standards/testing/README.md's three-layer pyramid, a change confined to adding string literals to _SHARED_INFRA_MODULES in src/adr_drift.py only needs a hermetic unit regression test.

Example: skip MockWorld scenario, sandbox e2e, and ADR-0049 kill-switch — no _citation_drifts/resolver/config edits, no phase-crossing behavior, no new loop/runner, no Ports touched. See also: Doc+single-unit-test fixes skip MockWorld/e2e.

**Why:** Those layers exist to catch loop-integration and orchestrator wiring bugs that a pure allowlist-data change cannot introduce.
