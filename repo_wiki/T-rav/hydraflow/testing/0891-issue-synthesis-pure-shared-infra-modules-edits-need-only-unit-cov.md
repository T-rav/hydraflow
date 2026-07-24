---
id: 0891
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:47:48.044583+00:00
status: active
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
---

# Pure _SHARED_INFRA_MODULES edits need only unit coverage, not MockWorld/e2e

Per `docs/standards/testing/README.md`'s three-layer pyramid, a change confined to adding string literals to `_SHARED_INFRA_MODULES` in `src/adr_drift.py` (no `_citation_drifts`/resolver/config edits, no phase-crossing behavior, no new loop/runner, no Ports touched) only needs a hermetic unit regression test.

Example: skip MockWorld scenario and sandbox e2e, and skip the ADR-0049 kill-switch.

**Why:** those layers exist to catch loop-integration and orchestrator wiring bugs that a pure allowlist-data change cannot introduce.
