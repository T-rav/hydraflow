---
id: 2729
topic: testing
source_issue: 11405
source_phase: plan
created_at: 2026-08-18T02:33:46.704137+00:00
status: active
corroborations: 1
---

# Use Skip-ADR trailer when no ADR owns the changed file

Rule: Ship with a `Skip-ADR:` commit trailer when a change touches a file mentioned only in prose by an ADR (e.g. `src/detector_calibration_loop.py` is referenced at `ADR-0126:21` but not owned by any ADR) and the behavior stays within the existing retrospective churn-miner contract.
- Confirm by checking ADR ownership: if no ADR owns the file and behavior is in-scope, skip a new ADR.

**Why:** Filing an ADR for in-contract behavior changes creates noise; the trailer records the decision without ceremony.
