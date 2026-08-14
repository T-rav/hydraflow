---
id: 2580
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.770567+00:00
status: active
corroborations: 1
supersedes: 2392
---

# ADR-0049 kill-switch: only for loop/worker/subprocess runners

The `HYDRAFLOW_DISABLE_<WORKER>_LOOP` env var plus `enabled_cb` callback (ADR-0049) applies to new loop/worker/subprocess runners only. Static test helpers like `src/spec_citation.py` do not need a kill-switch because they run in-process under pytest, not as persistent loops.

**Why:** Adding kill-switch plumbing to non-loop utilities is over-engineering and dilutes the ADR-0049 contract.
