---
id: 1123
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T08:27:46.934173+00:00
status: superseded
corroborations: 1
supersedes: 1054
superseded_by: 1191
---

# Per-tick issue-filing caps gate filing only, not accumulation

A `max_issues_per_tick`-style cap (e.g. `wiki_rot_detector_max_issues_per_tick` in `src/config.py`) must bound only the filing call count, not accumulation into the tracking set (`broken_subjects` for wiki-rot). Cap-suppressed subjects must still be added to `broken_subjects`.

Example: Mirrors `escape_ledger_max_issues_per_tick`, whose ledger recording is never capped. `reconcile_open`'s auto-close reads `broken_subjects`, so an omitted subject reads as "resolved" and its still-open escalation gets closed.

**Why:** Conflating "don't file yet" with "not broken anymore" makes `reconcile_open` wrongly close live escalations that are merely rate-limited.
