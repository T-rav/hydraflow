---
id: 0188
topic: architecture
source_issue: 10443
source_phase: plan
created_at: 2026-07-24T11:10:04.090214+00:00
status: active
corroborations: 1
---

# ADR citations need path:Symbol in one backtick span, not two

`adr_index._SOURCE_FILE_CITATION_RE` only binds a `:Symbol` tail when the path and symbol sit in the same backtick span. Writing `` `src/file.py` — `Class.method` `` (two spans) parses as a bare file citation with an empty symbol set, which makes `adr_drift._citation_drifts` treat the ADR as owning the whole file — so any unrelated churn to that file drifts it. Fix by merging into one span: `` `src/file.py:Class.method` `` (see ADR-0055:107 and `src/base_background_loop.py`). **Why:** this parsing quirk is the root cause behind needing `_SHARED_INFRA_MODULES` entries at all — fixing the span removes the false positive instead of masking it.
