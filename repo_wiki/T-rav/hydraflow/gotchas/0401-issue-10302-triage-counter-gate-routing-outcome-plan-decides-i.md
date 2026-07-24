---
id: 0401
topic: gotchas
source_issue: 10302
source_phase: plan
created_at: 2026-07-24T03:55:54.536778+00:00
status: active
corroborations: 1
---

# Triage counter gate: `routing_outcome == "plan"` decides `increment_session_counter("triaged")`

In `src/triage_phase.py`, the `"triaged"` session counter is only incremented when `routing_outcome == "plan"` (line ~547-550), not whenever an issue finishes triage. `_maybe_decompose(issue, result)` returning True sets `routing_outcome = "epic_decomposed"` (line 383) and short-circuits past that gate, so decomposed issues are deliberately excluded from the triaged count. `_triage_adr` (ADR fast-path) and `_triage_single_traced` (normal path) are the two call sites that can reach the `routing_outcome == "plan"` branch.

**Why:** anyone adding a new triage routing outcome needs to know the counter is opt-in via `"plan"`, not opt-out, or they'll silently miscount session stats.
