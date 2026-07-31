---
id: 2352
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.108698+00:00
status: active
corroborations: 1
supersedes: 2208
---

# _add_tool_call is the cross-backend span-event funnel

Emit bridged span events at `_add_tool_call` (`src/trace_collector.py:230`), the single site where Claude content-block tool calls, Codex `item.completed`, and Pi `tool_execution_start` converge.

Example: `bridge_event_to_span` (`src/telemetry/subprocess_bridge.py:30`) only matches top-level `type == "tool_use"` — emit `{"type": "tool_use", "tool": <name>, "name": <tool_use_id>}` so the bridge contract and its unit tests stay untouched.

**Why:** Emitting at the funnel avoids duplicating per-backend content-block parsing and keeps `bridge_event_to_span` stable.
