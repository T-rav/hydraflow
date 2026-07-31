---
id: 1717
topic: testing
source_issue: 10861
source_phase: plan
created_at: 2026-07-31T01:46:44.758672+00:00
status: active
corroborations: 1
---

# ADR attribution regex: match 4 forms, reject digit-prefix false positives

Attribution detection in `src/adr_conformance.py` must match exactly four forms: `ADR-0116`, `ADR 116`, bare `0116`, and a `docs/adr/0116-…md` path. A file containing only `10116` must NOT count as attributing ADR-0116.

- Pin all four positive forms plus the negative in `tests/test_adr_enforcement_classify.py`.

**Why:** Too-loose regex causes fake attribution and baseline churn; too-tight misses legitimate `ADR 116` and path forms, inflating the unattributed count.
