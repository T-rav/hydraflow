---
id: 1429
topic: gotchas
source_issue: 11307
source_phase: plan
created_at: 2026-08-16T05:25:13.887910+00:00
status: active
corroborations: 1
---

# Harvest objective changes via bounded subprocess and adr_index

Isolate data harvesting from the pure engine, bounding all `git log` calls.
- `src/objective_change_sources.py` uses `subprocess_util.run_subprocess_result` (following `principles_audit_loop` precedent) to parse `control/setpoints.yaml` and `control/principles.yaml` changes.
- Pull ADR supersessions from `adr_index`.
**Why:** Prevents unbounded subprocess hangs and keeps the issue body falsifiable via timestamp, signer, and ref.
