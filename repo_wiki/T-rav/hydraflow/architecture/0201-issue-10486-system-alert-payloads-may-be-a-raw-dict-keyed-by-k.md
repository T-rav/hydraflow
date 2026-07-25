---
id: 0201
topic: architecture
source_issue: 10486
source_phase: review
created_at: 2026-07-24T22:14:13.479953+00:00
status: stale
corroborations: 1
stale_reason: source issue #10486 closed
---

# SYSTEM_ALERT payloads may be a raw dict keyed by `kind`, not just SystemAlertPayload

`HydraFlowEvent.data` is typed `Mapping[str, Any]` (src/events.py:133), so `SYSTEM_ALERT` emitters can legitimately publish either `SystemAlertPayload(...)` or a raw dict literal with a custom `kind`. `cost_budget_alerts.py`, `prompt_gate_alerts.py`, `merge_state_watcher_loop.py`, and `runs_gc_loop.py` all use the raw-dict form and set `message`/`severity` themselves; `unpushed_branch_alert.py` follows the same pattern. `SystemAlertPayload` only models the fixed well-known fields — bespoke payload shapes (branch lists, break records, cost thresholds) use the dict form instead.

**Why:** Flagging a raw-dict `SYSTEM_ALERT` payload as missing `SystemAlertPayload(...)` is a false-positive review nit — both conventions coexist by design.
