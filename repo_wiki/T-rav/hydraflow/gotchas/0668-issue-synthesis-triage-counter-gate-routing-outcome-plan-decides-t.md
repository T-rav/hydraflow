---
id: 0668
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.462430+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# Triage counter gate: routing_outcome == "plan" decides the triaged counter

In `src/triage_phase.py`, the `"triaged"` session counter (`increment_session_counter`) is only incremented when `routing_outcome == "plan"` (line ~547-550), not whenever an issue finishes triage.

Example: `_maybe_decompose(issue, result)` returning True sets `routing_outcome = "epic_decomposed"` (line 383) and short-circuits past that gate, so decomposed issues are deliberately excluded. `_triage_adr` and `_triage_single_traced` are the two call sites that can reach the `"plan"` branch.

**Why:** Anyone adding a new triage routing outcome needs to know the counter is opt-in via `"plan"`, not opt-out, or they'll silently miscount session stats.
