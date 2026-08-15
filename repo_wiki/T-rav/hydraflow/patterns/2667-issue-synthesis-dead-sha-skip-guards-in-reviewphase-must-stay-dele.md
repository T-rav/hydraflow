---
id: 2667
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T08:32:49.070479+00:00
status: superseded
corroborations: 1
supersedes: 2545
superseded_by: 2790
---

# Dead SHA skip guards in ReviewPhase must stay deleted

Do not re-wire any SHA-based skip guard around `last_reviewed_sha` in `src/review_phase/_phase.py`. PR #2200 removed the live twin `_should_skip_review` because PRs labeled hydraflow-review were silently skipped and dropped from tracking; `_check_sha_skip_guard` survived only because it was already orphaned. When deleting such a method, add a comment at the `set_last_reviewed_sha` write site in `_record_review_outcome` citing #2200/#11223 so future readers don't "repair" the write-only value.

**Why:** Any skip-on-unchanged-head-SHA variant regresses the #2200 outage and requires a new ADR, not a code change.
