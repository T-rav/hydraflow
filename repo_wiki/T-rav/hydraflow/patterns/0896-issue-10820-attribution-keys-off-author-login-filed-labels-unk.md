---
id: 0896
topic: patterns
source_issue: 10820
source_phase: plan
created_at: 2026-07-31T00:58:39.724675+00:00
status: superseded
corroborations: 1
superseded_by: 0953
---

# Attribution keys off author login + filed_labels; unknown is reported

Attribution in `src/stillness/series.py` keys off author login plus `filed_labels` from `docs/arch/loop_signal_classification.yml`. Unmapped authors bucket to `unknown` and are surfaced in the report artifact, never silently counted as external.

**Why:** Misclassifying internal contributors as external would inflate the self-sourced fraction and skew the flux-share ranking.
