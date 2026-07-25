---
id: 0851
topic: gotchas
source_issue: 10516
source_phase: plan
created_at: 2026-07-25T05:52:44.074228+00:00
status: active
corroborations: 1
---

# HITL events need an event-aware status resolver, not the generic status branch

In `useTimeline.js`, the generic status branch (~line 152-164) maps raw event `status` to stage status directly, but HITL events don't fit: `hitl_escalation` carries `status: "diagnostic"` (`src/review_phase/_phase.py:3299`) or no status at all (`src/dashboard_routes/_routes.py:1790`), and `hitl_update` carries `running|done|resolved|failed|pending` where `failed`/`pending` mean "still needs a human," not "the stage failed." Mirror the backend's `_normalise_event_status` (`src/dashboard_routes/_routes.py:205`) with a small resolver applied before the generic branch: escalation → always `hitl`; update → `done` on `done|resolved`, else `hitl`.

**Why:** letting the generic branch handle HITL events flips `overallStatus` to `failed` on a recoverable auto-correction failure.
