---
id: 0544
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.248398+00:00
status: superseded
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
superseded_by: 0550
---

# adr_drift nudge fan-out denominator must filter before counting, not just emitting

`bare_infra_citation_nudges` in `src/adr_drift.py` must filter `adr_list` to live ADRs *before* both the per-ADR emit loop and the `_bare_citation_fanout` count. Filtering only in the emit loop still lets non-live ADRs inflate the fan-out denominator above the #10456 threshold, causing live ADRs that genuinely drift to be skipped instead of nudged. See also: patterns — ADR-drift threshold configs must thread to both auditor call sites.

**Why:** a half-fix (filter emit, not count) trades one false-positive class for a false-negative class in the same function.
