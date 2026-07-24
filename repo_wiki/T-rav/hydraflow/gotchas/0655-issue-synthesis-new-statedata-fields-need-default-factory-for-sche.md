---
id: 0655
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.443288+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# New StateData fields need default_factory for schema-evolution safety

New optional dict/list fields on `StateData` (`src/models.py`) must use `Field(default_factory=dict)` (or equivalent), e.g. `triage_park_class: dict[str, str] = Field(default_factory=dict)`. This lets Pydantic populate the field when loading state files written before the field existed, instead of failing validation.

**Why:** hydraflow persists `StateData` across releases (ADR-0021); a required or no-default field breaks deserialization of every pre-existing state file on deploy.
