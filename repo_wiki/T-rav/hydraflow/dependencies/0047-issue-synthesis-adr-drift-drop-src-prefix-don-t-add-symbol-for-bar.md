---
id: 0047
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:48:28.316452+00:00
status: superseded
corroborations: 1
supersedes: 0041
superseded_by: 0054
---

# ADR drift: drop src/ prefix, don't add :Symbol, for bare citations

When an ADR's prose names a high-churn file it doesn't own (e.g. ADR-0106 mentioning `src/base_background_loop.py`), `_SOURCE_FILE_CITATION_RE` in `src/adr_drift.py` records it as a bare citation and `_citation_drifts` false-positives on every unrelated touch. Fix by removing the `src/` prefix from the prose mention so the regex no longer matches.

Example: same shape as #10434 (ADR-0055) and #10441 (ADR-0106) — do NOT add a `:Symbol` tail, since that falsely claims ownership instead of eliminating the FP. See also: gotchas — ADR-drift shared-infra allowlist.

**Why:** Dropping the prefix removes the file from `source_files` entirely; adding a symbol tail keeps a false ownership claim alive.
