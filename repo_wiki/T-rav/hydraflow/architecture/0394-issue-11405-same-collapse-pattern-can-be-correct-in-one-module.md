---
id: 0394
topic: architecture
source_issue: 11405
source_phase: plan
created_at: 2026-08-18T02:33:46.704143+00:00
status: active
corroborations: 1
---

# Same collapse pattern can be correct in one module, wrong in another

Rule: Before filing a class-wide defect, verify that the same code pattern has the same semantic role in each module. `src/detector_calibration_loop.py:_normalize` collapses `#N` incorrectly because PR refs are entity identity there; `src/log_ingest_loop.py:132` collapses `#N` correctly because it clusters identical log messages across entities.
- Same regex, different intent — not a same-class defect.

**Why:** Treating every pattern instance as a class defect wastes investigation and risks breaking correct behavior in sibling modules.
