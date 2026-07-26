---
id: 1033
topic: gotchas
source_issue: 10561
source_phase: plan
created_at: 2026-07-25T23:57:26.301185+00:00
status: superseded
corroborations: 1
superseded_by: 1039
---

# EscapeCandidate.id folds in detection_source, so latest_by_id can't dedup

In `src/escape/metrics.py`, `EscapeCandidate.id` embeds `detection_source` (e.g. `bug-issue:sha` vs `regression-pin:sha`), so `latest_by_id()` treats re-detection of the same commit under a stronger source as a brand-new row instead of a correction. Live effect: `.hydraflow/diagnostics/escape_ledger.jsonl` held two rows each for commits `ee566772…` and `055267e7…`. Fix keys identity on the escaping commit (`detection_ref`) via a new `latest_by_escape` in metrics, not on the source-qualified id.

**Why:** an id scheme that encodes *how* something was detected, not *what* was detected, breaks any later attempt to correct a stale low-confidence classification.
