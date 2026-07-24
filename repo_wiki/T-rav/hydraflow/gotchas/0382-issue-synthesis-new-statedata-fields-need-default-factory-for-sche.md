---
id: 0382
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.388235+00:00
status: superseded
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
superseded_by: 0402
---

# New StateData fields need default_factory for schema-evolution safety

New optional dict/list fields on `StateData` (`src/models.py`) must use `Field(default_factory=dict)` (or equivalent), e.g. `triage_park_class: dict[str, str] = Field(default_factory=dict)`. This lets Pydantic populate the field when loading state files written before the field existed, instead of failing validation.

**Why:** hydraflow persists `StateData` across releases (ADR-0021); a required or no-default field breaks deserialization of every pre-existing state file on deploy.
