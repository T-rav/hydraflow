---
id: 0570
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.778018+00:00
status: superseded
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
superseded_by: 0584
---

# adr_drift nudge fan-out: filter before counting, not just before emitting

`bare_infra_citation_nudges` in `src/adr_drift.py` must filter `adr_list` to live ADRs *before* both the per-ADR emit loop and the `_bare_citation_fanout` count. Filtering only in the emit loop still lets non-live ADRs inflate the fan-out denominator above the #10456 threshold, causing live ADRs that genuinely drift to be skipped instead of nudged. See also: patterns — ADR-drift threshold configs must thread to both auditor call sites.

**Why:** a half-fix (filter emit, not count) trades one false-positive class for a false-negative class in the same function.
