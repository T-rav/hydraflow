---
id: 0576
topic: patterns
source_issue: 10586
source_phase: plan
created_at: 2026-07-26T02:51:38.701769+00:00
status: superseded
corroborations: 1
superseded_by: 0610
---

# Per-tick issue-filing caps must gate filing only, not subject accumulation

A `max_issues_per_tick`-style cap (e.g. `wiki_rot_detector_max_issues_per_tick` in `src/config.py`) must bound only the filing call count, not accumulation into the tracking set (`broken_subjects` for wiki-rot). Mirrors `escape_ledger_max_issues_per_tick`, whose ledger recording is never capped. Cap-suppressed subjects must still be added to `broken_subjects`; `reconcile_open`'s auto-close logic reads that set, so an omitted subject reads as "resolved" and its still-open escalation gets closed.

**Why:** conflating "don't file yet" with "not broken anymore" makes `reconcile_open` wrongly close live escalations that are merely rate-limited.
