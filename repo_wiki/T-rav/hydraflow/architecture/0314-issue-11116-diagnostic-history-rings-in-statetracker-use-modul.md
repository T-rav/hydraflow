---
id: 0314
topic: architecture
source_issue: 11116
source_phase: plan
created_at: 2026-08-14T10:10:56.158106+00:00
status: active
corroborations: 1
---

# Diagnostic history rings in StateTracker use module-constant caps

State-tracking diagnostic rings (e.g. `prompt_efficiency_baseline_history`) are bounded by a module constant, not config — `StateTracker.__init__` takes no config. Keep per-inference detail in `metrics/prompt/inferences.jsonl`; the ring is state, not a metrics store.

**Why:** Unbounded state growth on long-running loops; config coupling would force a constructor signature change.
