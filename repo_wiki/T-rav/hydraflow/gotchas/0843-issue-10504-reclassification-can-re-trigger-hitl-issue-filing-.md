---
id: 0843
topic: gotchas
source_issue: 10504
source_phase: plan
created_at: 2026-07-25T02:18:04.061457+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# Reclassification can re-trigger HITL issue filing via record-id fingerprinting

The escape ledger's surfacing fingerprint is keyed on record id, which changes when a commit is reclassified (e.g. `bug-issue` → `regression-pin` after a detector fix). A re-baseline rewind that re-reads and reclassifies historical commits can therefore re-file HITL issues that were already surfaced under the old classification — potentially duplicating issues like #10498/#10499 and burning `escape_ledger_max_issues_per_tick` on repeats rather than new escapes. Any re-baseline change (`DETECTOR_GENERATION` rewind in `escape_ledger_loop.py`) must include a test proving no double-filing across a reclassification. **Why:** fingerprint-on-id is a hidden coupling between classification correctness and issue-filing idempotency that only surfaces when the classifier itself changes.
