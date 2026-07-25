---
id: 0997
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:21:18.145896+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952
---

# Pure _SHARED_INFRA_MODULES edits need only unit coverage, not MockWorld/e2e

Per `docs/standards/testing/README.md`'s three-layer pyramid, a change confined to adding string literals to `_SHARED_INFRA_MODULES` in `src/adr_drift.py` (no `_citation_drifts`/resolver/config edits, no phase-crossing behavior, no new loop/runner, no Ports touched) only needs a hermetic unit regression test — skip MockWorld scenario and sandbox e2e, and skip the ADR-0049 kill-switch.

**Why:** those layers exist to catch loop-integration and orchestrator wiring bugs that a pure allowlist-data change cannot introduce.
