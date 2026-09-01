---
id: 1554
topic: gotchas
source_issue: 11889
source_phase: plan
created_at: 2026-09-01T10:19:26.410403+00:00
status: active
corroborations: 1
---

# Verify wire-format field names against vendor schemas, not assumptions

Pi's `tool_execution_end` carries `toolCallId`; `src/trace_collector.py` read `invocationId` (no such field), so Pi spans never opened. Codex's current `item.completed` types were unhandled while only legacy `function_call` was parsed.

Before parsing a vendor event, confirm the field name against the vendor's schema doc or a captured fixture (e.g., `codex app-server generate-json-schema`).

**Why:** A name mismatch silently zeroes the backend's `tool_errors`, making `retro_signals` treat the entire span as an unreadable gap.
