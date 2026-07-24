---
id: 0618
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.260515+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Triage counter gate: routing_outcome == "plan" decides the triaged counter

In `src/triage_phase.py`, the `"triaged"` session counter (`increment_session_counter`) is only incremented when `routing_outcome == "plan"` (line ~547-550), not whenever an issue finishes triage.

Example: `_maybe_decompose(issue, result)` returning True sets `routing_outcome = "epic_decomposed"` (line 383) and short-circuits past that gate, so decomposed issues are deliberately excluded. `_triage_adr` and `_triage_single_traced` are the two call sites that can reach the `"plan"` branch.

**Why:** Anyone adding a new triage routing outcome needs to know the counter is opt-in via `"plan"`, not opt-out, or they'll silently miscount session stats.
