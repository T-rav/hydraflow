---
id: 0471
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.395686+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
---

# Triage counter gate: routing_outcome == "plan" decides the triaged counter

In `src/triage_phase.py`, the `"triaged"` session counter (`increment_session_counter`) is only incremented when `routing_outcome == "plan"` (line ~547-550), not whenever an issue finishes triage. `_maybe_decompose(issue, result)` returning True sets `routing_outcome = "epic_decomposed"` (line 383) and short-circuits past that gate, so decomposed issues are deliberately excluded from the triaged count. `_triage_adr` (ADR fast-path) and `_triage_single_traced` (normal path) are the two call sites that can reach the `routing_outcome == "plan"` branch.

**Why:** anyone adding a new triage routing outcome needs to know the counter is opt-in via `"plan"`, not opt-out, or they'll silently miscount session stats.
