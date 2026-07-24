---
id: 0427
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.298488+00:00
status: superseded
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
superseded_by: 0446
---

# Triage counter gate: routing_outcome == "plan" decides the triaged counter

In `src/triage_phase.py`, the `"triaged"` session counter (`increment_session_counter`) is only incremented when `routing_outcome == "plan"` (line ~547-550), not whenever an issue finishes triage. `_maybe_decompose(issue, result)` returning True sets `routing_outcome = "epic_decomposed"` (line 383) and short-circuits past that gate, so decomposed issues are deliberately excluded from the triaged count. `_triage_adr` (ADR fast-path) and `_triage_single_traced` (normal path) are the two call sites that can reach the `routing_outcome == "plan"` branch.

**Why:** anyone adding a new triage routing outcome needs to know the counter is opt-in via `"plan"`, not opt-out, or they'll silently miscount session stats.
