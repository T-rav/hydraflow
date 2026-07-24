---
id: 0195
topic: architecture
source_issue: 10456
source_phase: plan
created_at: 2026-07-24T12:31:36.987736+00:00
status: active
corroborations: 1
---

# Fan-out threshold field must enforce ge=2 — fanout counts the citing ADR itself

`adr_drift_shared_infra_fanout_threshold` in `src/config.py` must be declared with Pydantic `ge=2`. `_bare_citation_fanout(path, adrs)` counts the citing ADR itself, so a threshold of 1 would suppress every single bare citation across the repo — the fan-out floor for "genuinely shared" starts at 2 co-citing ADRs, not 1.

**Why:** an unguarded threshold=1 turns fan-out suppression into a global bare-citation kill switch, masking real ADR drift for modules cited by only one ADR.
