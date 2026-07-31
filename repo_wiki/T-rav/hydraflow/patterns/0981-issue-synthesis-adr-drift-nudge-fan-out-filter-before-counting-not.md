---
id: 0981
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:11:10.515347+00:00
status: active
corroborations: 1
supersedes: 0917
---

# adr_drift nudge fan-out: filter before counting, not just emitting

`bare_infra_citation_nudges` in `src/adr_drift.py` must filter `adr_list` to live ADRs *before* both the per-ADR emit loop and the `_bare_citation_fanout` count.

Example: Filtering only in the emit loop lets non-live ADRs inflate the fan-out denominator above the #10456 threshold, causing live ADRs that genuinely drift to be skipped. See also: patterns — ADR-drift threshold configs must thread to both auditor call sites.

**Why:** A half-fix (filter emit, not count) trades one false-positive class for a false-negative class in the same function.
