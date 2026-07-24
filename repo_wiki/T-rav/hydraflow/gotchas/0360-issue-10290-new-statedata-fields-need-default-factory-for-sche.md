---
id: 0360
topic: gotchas
source_issue: 10290
source_phase: plan
created_at: 2026-07-22T17:18:40.189885+00:00
status: superseded
corroborations: 1
superseded_by: 0370
---

# New StateData fields need default_factory for schema-evolution safety

New optional dict/list fields on `StateData` (`src/models.py`) must use `Field(default_factory=dict)` (or equivalent), e.g. `triage_park_class: dict[str, str] = Field(default_factory=dict)`. This lets Pydantic populate the field when loading state files written before the field existed, instead of failing validation.

**Why:** hydraflow persists `StateData` across releases (ADR-0021); a required or no-default field breaks deserialization of every pre-existing state file on deploy.
