---
id: 0953
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:33:17.986433+00:00
status: superseded
corroborations: 1
supersedes: 0896
superseded_by: 1017
---

# Attribution keys off author login + filed_labels; unknown is reported

Attribution in `src/stillness/series.py` keys off author login plus `filed_labels` from `docs/arch/loop_signal_classification.yml` — unmapped authors bucket to `unknown` and are surfaced in the report artifact, never silently counted as external.

Example: An internal contributor with an unmapped login appears as `unknown` in the report, not silently counted as external.

**Why:** Misclassifying internal contributors as external would inflate the self-sourced fraction and skew the flux-share ranking.
