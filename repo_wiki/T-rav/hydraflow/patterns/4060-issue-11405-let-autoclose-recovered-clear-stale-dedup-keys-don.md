---
id: 4060
topic: patterns
source_issue: 11405
source_phase: plan
created_at: 2026-08-18T02:33:46.704130+00:00
status: active
corroborations: 1
---

# Let _autoclose_recovered clear stale dedup keys, don't hand-edit JSON

Rule: After fixing subject normalization in `src/detector_calibration_loop.py`, do not hand-edit `data/dedup/detector_calibration.json`. Stale keys (e.g. `pr ## (gauntlet)`) become unreachable in `churning` and `_autoclose_recovered` closes the open finding and drops the digest on the next uncapped, non-empty tick.
- Read `_autoclose_recovered` to confirm the path; trust the loop, not manual edits.

**Why:** Hand-editing dedup stores bypasses the audit trail and risks dropping still-valid digests.
