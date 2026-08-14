---
id: 2542
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.202020+00:00
status: active
corroborations: 1
supersedes: 2353
---

# _record_inner pass-through + funnel emit don't double-fire

Keep both emit paths: the `_record_inner` bridge pass-through (`src/trace_collector.py:97-103`) and `_add_tool_call` emission do NOT double-fire span events.

Example: invariant — no top-level `type == "tool_use"` event reaches `_add_tool_call`, so the two paths are disjoint. Guard with a count-equality test: `claude.tool` event count == recorded tool-call count for `claude_implement_sample.jsonl`.

**Why:** Removing the pass-through breaks the documented bridge contract; removing the funnel emit reintroduces bridge inertness. Both paths are load-bearing and the disjointness is non-obvious.
