---
id: 0597
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.341636+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# ADR-drift threshold configs must thread to both auditor call sites

`src/adr_touchpoint_auditor_loop.py` calls drift computation from both the main scan (`partition_fleet_drift`) and stale-rollup reconcile (`compute_drift_by_adr`). Any new config-driven threshold must be passed to both.

Example: pass the same `shared_infra_fanout_threshold` value into both call sites. See also: patterns — adr_drift nudge fan-out: filter before counting.

**Why:** if reconcile doesn't receive the same threshold as the main scan, a fan-out-suppressed rollup strands open forever instead of auto-closing.
