---
id: 1059
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.539067+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# Pure _SHARED_INFRA_MODULES edits need only unit coverage, not MockWorld/e2e

Per docs/standards/testing/README.md's three-layer pyramid, a change confined to adding string literals to _SHARED_INFRA_MODULES in src/adr_drift.py (no _citation_drifts/resolver/config edits, no phase-crossing behavior, no new loop/runner, no Ports touched) only needs a hermetic unit regression test.

Example: skip MockWorld scenario and sandbox e2e, and skip the ADR-0049 kill-switch.

**Why:** those layers exist to catch loop-integration and orchestrator wiring bugs that a pure allowlist-data change cannot introduce.
