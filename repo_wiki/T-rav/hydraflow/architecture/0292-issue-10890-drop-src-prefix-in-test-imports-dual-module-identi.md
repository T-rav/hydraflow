---
id: 0292
topic: architecture
source_issue: 10890
source_phase: plan
created_at: 2026-07-31T12:12:42.365106+00:00
status: active
corroborations: 1
---

# Drop `src.` prefix in test imports — dual module identity diverges state

Drop the `src.` prefix when importing `telemetry.*` or `trace_collector` in tests. The prefixed path loads a separate module object from production, diverging module-level singletons (loggers, caches).

- Bad: `tests/test_telemetry_subprocess_bridge.py:13` → `from src.telemetry.subprocess_bridge import bridge_event_to_span`
- Good: `from telemetry.subprocess_bridge import bridge_event_to_span`

**Why:** Dual identity hides state-divergence bugs that only manifest when production and test paths touch the same module-level singleton (#10874).
