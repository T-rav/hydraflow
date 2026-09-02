---
id: 1555
topic: gotchas
source_issue: 11889
source_phase: plan
created_at: 2026-09-01T10:19:26.410487+00:00
status: active
corroborations: 1
---

# ToolCallSpan semantics must be backend-agnostic for retro_signals

`succeeded`, `error`, and `tool_errors` must mean the same thing for Claude, Pi, and Codex. Close every backend's span from its real completion event via a single `_close_span` helper in `src/trace_collector.py` rather than leaving non-Claude spans open.

`src/retro_signals.py`'s `_tool_errors` rationale must not special-case backends as "never closed" — update the comment when the gap is closed.

**Why:** Backend-specific gap logic in signal generation masks missing error data and rots when collectors are fixed.
