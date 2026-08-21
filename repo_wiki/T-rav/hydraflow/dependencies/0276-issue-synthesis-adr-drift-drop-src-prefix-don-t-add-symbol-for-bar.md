---
id: 0276
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-18T13:47:37.723437+00:00
status: active
corroborations: 1
supersedes: 0258
---

# ADR drift: drop src/ prefix, don't add :Symbol, for bare citations

When an ADR's prose names a high-churn file it doesn't own, drop the `src/` prefix so `_SOURCE_FILE_CITATION_RE` in `src/adr_drift.py` no longer matches it as a bare citation — do NOT add a `:Symbol` tail.

Example: ADR-0106 mentioning `src/base_background_loop.py` causes `_citation_drifts` to false-positive on every unrelated touch. See also: gotchas — ADR-drift shared-infra allowlist; dependencies — _follow_reexports reuses _collect_defined_symbols helper.

**Why:** Dropping the prefix removes the file from `source_files` entirely; adding a symbol tail keeps a false ownership claim alive.
