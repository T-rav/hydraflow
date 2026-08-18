---
id: 2756
topic: testing
source_issue: 11427
source_phase: plan
created_at: 2026-08-18T04:40:50.671689+00:00
status: active
corroborations: 1
---

# DetectorCalibrationLoop findings need disjoint dedup keys per class

Finding classes in `DetectorCalibrationLoop` must use disjoint dedup namespaces and disjoint body key lines. Spray findings carry `Template-Key:`; subject findings carry `Norm-Key:`.

- `_autoclose_recovered` must test `Template-Key:` before `Norm-Key:` — matching the spray body against the subject dict first auto-closes every spray finding on the tick after filing.
- One entity re-firing 20× must produce a subject finding, never a spray finding.

**Why:** A shared or misordered dedup namespace causes one finding class to silently close the other, defeating the class separation.
