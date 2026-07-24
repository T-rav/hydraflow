---
id: 0940
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:10:19.636432+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# Pure _SHARED_INFRA_MODULES edits need only unit coverage, not MockWorld/e2e

Per `docs/standards/testing/README.md`'s three-layer pyramid, a change confined to adding string literals to `_SHARED_INFRA_MODULES` in `src/adr_drift.py` (no `_citation_drifts`/resolver/config edits, no phase-crossing behavior, no new loop/runner, no Ports touched) only needs a hermetic unit regression test — skip MockWorld scenario and sandbox e2e, and skip the ADR-0049 kill-switch.

**Why:** those layers exist to catch loop-integration and orchestrator wiring bugs that a pure allowlist-data change cannot introduce.
