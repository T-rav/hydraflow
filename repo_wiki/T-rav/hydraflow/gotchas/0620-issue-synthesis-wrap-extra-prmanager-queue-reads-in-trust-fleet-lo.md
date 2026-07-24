---
id: 0620
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.455647+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Wrap extra PRManager queue reads in trust-fleet loops fail-open

Any new `PRManager` call added inside a `TrustFleetSanityLoop` tick (e.g. `list_issues_by_label`) must be wrapped to fail open — return an empty result and let the cycle complete — mirroring the existing `_reconcile_closed_escalations` pattern.

Example: `_collect_hitl_queue_signal()` in `src/trust_fleet_sanity_loop.py` catches `list_issues_by_label` exceptions and treats them as an empty queue rather than propagating.

**Why:** An unguarded hang or exception on the extra gh/API call would trip the dead-man-switch and stall the whole sanity loop, not just the new detector.
