---
id: 0009
topic: dependencies
source_issue: 10441
source_phase: plan
created_at: 2026-07-24T10:43:53.901975+00:00
status: active
corroborations: 1
---

# ADR drift: fix bare source-file citations by dropping `src/`, never adding `:Symbol`

When an ADR's prose names a high-churn file it doesn't own (e.g. ADR-0106 mentioning `src/base_background_loop.py` as a dependency pointer, not its decision site), `_SOURCE_FILE_CITATION_RE` in `src/adr_drift.py` records it as a bare (empty-symbol) citation, and `_citation_drifts` then false-positive-drifts on every unrelated touch of that file. Fix by removing the `src/` prefix from the prose mention so the regex no longer matches — do NOT add a `:Symbol` tail, since that falsely claims ownership and just narrows the FP instead of eliminating it. Same shape as #10434 (ADR-0055) and #10441 (ADR-0106).
**Why:** dropping the prefix removes the file from `source_files` entirely; adding a symbol tail keeps a false ownership claim alive.
