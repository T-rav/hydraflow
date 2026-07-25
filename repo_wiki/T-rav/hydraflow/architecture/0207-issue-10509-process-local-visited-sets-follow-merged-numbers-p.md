---
id: 0207
topic: architecture
source_issue: 10509
source_phase: review
created_at: 2026-07-25T09:54:20.029592+00:00
status: active
corroborations: 1
---

# Process-local visited-sets follow `_merged_numbers` precedent, not durable state

New in-memory tracking sets like `_hitl_visited` (populated only by explicit event handlers, not GitHub-label polling) mirror the existing `_merged_numbers` pattern and are expected to be process-local/non-persistent across restarts — this is established precedent, not a new gap. Durable HITL state lives in `src/state/_hitl.py` and is cleared on resolution via `clear_hitl_state`, so it cannot substitute for the in-memory set (different lifecycle, not redundant).

**Why:** avoids mis-flagging restart-loses-state as a regression when it matches an accepted existing pattern in the same module family.
