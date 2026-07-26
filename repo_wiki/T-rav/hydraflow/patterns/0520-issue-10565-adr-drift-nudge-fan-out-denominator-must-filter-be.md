---
id: 0520
topic: patterns
source_issue: 10565
source_phase: plan
created_at: 2026-07-25T23:03:04.264290+00:00
status: active
corroborations: 1
---

# adr_drift nudge fan-out denominator must filter before counting, not just before emitting

`bare_infra_citation_nudges` in `src/adr_drift.py` must filter `adr_list` to live ADRs *before* both the per-ADR emit loop and the `_bare_citation_fanout` count. Filtering only in the emit loop still lets non-live ADRs inflate the fan-out denominator above the #10456 threshold, causing live ADRs that genuinely drift to be skipped instead of nudged.

**Why:** a half-fix (filter emit, not count) trades one false-positive class for a false-negative class in the same function.
