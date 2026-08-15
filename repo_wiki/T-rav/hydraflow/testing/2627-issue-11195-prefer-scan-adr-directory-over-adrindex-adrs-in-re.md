---
id: 2627
topic: testing
source_issue: 11195
source_phase: plan
created_at: 2026-08-15T01:07:17.473982+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Prefer scan_adr_directory over ADRIndex.adrs() in regression fixtures

Use `scan_adr_directory` directly in regression test fixtures that reproduce unfiltered-corpus behavior, not `ADRIndex.adrs()`.

- `ADRIndex.adrs()` merely delegates to `scan_adr_directory`, so switching buys nothing.
- `arch.runner` and `adr_cross_reference` both drive the same unfiltered corpus.
- Switching weakens fixture fidelity and can mask the reproduction path.

**Why:** Routing through `ADRIndex` discards the unfiltered-corpus property that makes the pin faithfully reproduce the original bug.
