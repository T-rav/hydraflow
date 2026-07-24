---
id: 0506
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.779406+00:00
status: superseded
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
superseded_by: 0545
---

# New StateData fields need default_factory for schema-evolution safety

New optional dict/list fields on `StateData` (`src/models.py`) must use `Field(default_factory=dict)` (or equivalent), e.g. `triage_park_class: dict[str, str] = Field(default_factory=dict)`. This lets Pydantic populate the field when loading state files written before the field existed, instead of failing validation.

**Why:** hydraflow persists `StateData` across releases (ADR-0021); a required or no-default field breaks deserialization of every pre-existing state file on deploy.
