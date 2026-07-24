---
id: 0473
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.397024+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0494
---

# Wrap extra PRManager queue reads in trust-fleet loops fail-open

Any new `PRManager` call added inside a `TrustFleetSanityLoop` tick (e.g. `list_issues_by_label`) must be wrapped to fail open — return an empty result and let the cycle complete — mirroring the existing `_reconcile_closed_escalations` pattern.

Example: `_collect_hitl_queue_signal()` in `src/trust_fleet_sanity_loop.py` catches `list_issues_by_label` exceptions and treats them as an empty queue rather than propagating.

**Why:** an unguarded hang or exception on the extra gh/API call would trip the dead-man-switch and stall the whole sanity loop, not just the new detector.
