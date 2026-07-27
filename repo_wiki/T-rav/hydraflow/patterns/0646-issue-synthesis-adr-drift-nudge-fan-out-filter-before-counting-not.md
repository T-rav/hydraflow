---
id: 0646
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:03:14.317070+00:00
status: superseded
corroborations: 1
supersedes: 0604
superseded_by: 0691
---

# adr_drift nudge fan-out: filter before counting, not just emitting

`bare_infra_citation_nudges` in `src/adr_drift.py` must filter `adr_list` to live ADRs *before* both the per-ADR emit loop and the `_bare_citation_fanout` count.

Example: Filtering only in the emit loop lets non-live ADRs inflate the fan-out denominator above the #10456 threshold, causing live ADRs that genuinely drift to be skipped. See also: patterns — ADR-drift threshold configs must thread to both auditor call sites.

**Why:** A half-fix (filter emit, not count) trades one false-positive class for a false-negative class in the same function.
