---
id: 0237
topic: architecture
source_issue: 10600
source_phase: plan
created_at: 2026-07-26T12:25:53.446780+00:00
status: active
corroborations: 1
---

# Never widen runtime_checkable SubprocessRunner protocol

Avoid widening the `runtime_checkable` `SubprocessRunner` protocol to pass per-spawn provider state — adding parameters breaks every fake in the test suite. Instead, use a Layer-1 stdlib-only module (`src/credit_fallback.py`) holding process-global binding that `DockerRunner` and `orchestrator` read directly. **Why:** Prevents cascading test breakage across all fake runner implementations for a single feature.
