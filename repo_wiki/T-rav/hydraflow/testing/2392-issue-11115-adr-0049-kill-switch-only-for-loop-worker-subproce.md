---
id: 2392
topic: testing
source_issue: 11115
source_phase: plan
created_at: 2026-08-14T10:03:17.496159+00:00
status: active
corroborations: 1
---

# ADR-0049 kill-switch: only for loop/worker/subprocess runners

The `HYDRAFLOW_DISABLE_<WORKER>_LOOP` env var plus `enabled_cb` callback (ADR-0049) applies to new loop/worker/subprocess runners only. Static test helpers like `src/spec_citation.py` do not need a kill-switch because they run in-process under pytest, not as persistent loops.

**Why:** Adding kill-switch plumbing to non-loop utilities is over-engineering and dilutes the ADR-0049 contract.
