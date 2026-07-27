---
id: 0041
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:32.729543+00:00
status: active
corroborations: 1
supersedes: 0035
---

# ADR drift: drop src/ prefix, don't add :Symbol, for bare citations

When an ADR's prose names a high-churn file it doesn't own (e.g. ADR-0106 mentioning `src/base_background_loop.py` as a dependency pointer), `_SOURCE_FILE_CITATION_RE` in `src/adr_drift.py` records it as a bare citation and `_citation_drifts` false-positives on every unrelated touch. Fix by removing the `src/` prefix from the prose mention so the regex no longer matches.

Example: same shape as #10434 (ADR-0055) and #10441 (ADR-0106) — do NOT add a `:Symbol` tail, since that falsely claims ownership instead of eliminating the FP. See also: gotchas — ADR-drift shared-infra allowlist.

**Why:** Dropping the prefix removes the file from `source_files` entirely; adding a symbol tail keeps a false ownership claim alive.
