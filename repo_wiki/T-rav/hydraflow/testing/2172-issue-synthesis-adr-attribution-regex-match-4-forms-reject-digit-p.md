---
id: 2172
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.380754+00:00
status: superseded
corroborations: 1
supersedes: 2043
superseded_by: 2317
---

# ADR attribution regex: match 4 forms, reject digit-prefix

Attribution detection in `src/adr_conformance.py` must match exactly four forms: `ADR-0116`, `ADR 116`, bare `0116`, and a `docs/adr/0116-…md` path. A file containing only `10116` must NOT count as attributing ADR-0116.

Example: pin all four positive forms plus the negative in `tests/test_adr_enforcement_classify.py`.

**Why:** Too-loose regex causes fake attribution and baseline churn; too-tight misses legitimate `ADR 116` and path forms, inflating the unattributed count.
