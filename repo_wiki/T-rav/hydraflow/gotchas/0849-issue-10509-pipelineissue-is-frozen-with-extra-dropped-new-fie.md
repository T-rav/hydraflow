---
id: 0849
topic: gotchas
source_issue: 10509
source_phase: plan
created_at: 2026-07-25T05:02:36.104095+00:00
status: active
corroborations: 1
---

# PipelineIssue is frozen with extra dropped — new fields need both Snapshot and Issue models

`PipelineIssue` is `frozen=True` with default `extra` behavior, so adding a field to only one of `PipelineSnapshotEntry` or `PipelineIssue` gets it silently dropped during validation at `src/_routes.py:1820` — no error, just missing data on the wire. Any new snapshot field (e.g. `hitl_visited`) must be added to both models in `src/models.py` and defaulted so old snapshots/clients stay compatible.

**Why:** Pydantic's default extra-field handling swallows unmodeled fields instead of erroring, turning a one-file edit into a silent partial fix.
