---
id: 0367
topic: architecture
source_issue: 11303
source_phase: plan
created_at: 2026-08-16T04:31:48.836019+00:00
status: active
corroborations: 1
---

# Load disturbance baselines fail-soft in diagnostic routes

Treat every `disturbance/baselines/*.yaml` load as fallible: a missing or unreadable baseline yields a degraded status block, never a 500.

- Engine layer: `TokenBaseline` load/save wraps YAML access in try/except and returns a no-baseline status with zero episodes.
- Route layer: `/api/diagnostics/token-report` renders a `drift` block with degraded status when the baseline is absent.

**Why:** A committed-baseline instrument that 500s on first deploy (before the baseline exists) blocks the entire diagnostic surface instead of just signalling "not yet pinned."
