---
id: 2954
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T20:34:47.766072+00:00
status: superseded
corroborations: 1
supersedes: 2827
superseded_by: 3088
---

# Per-tick issue-filing caps gate filing only, not accumulation

A `max_issues_per_tick`-style cap (e.g. `wiki_rot_detector_max_issues_per_tick` in `src/config.py`) must bound only the filing call count, not accumulation into the tracking set (`broken_subjects` for wiki-rot). Cap-suppressed subjects must still be added to `broken_subjects`.

Example: Mirrors `escape_ledger_max_issues_per_tick`, whose ledger recording is never capped. `reconcile_open`'s auto-close reads `broken_subjects`, so an omitted subject reads as "resolved" and its still-open escalation gets closed.

**Why:** Conflating "don't file yet" with "not broken anymore" makes `reconcile_open` wrongly close live escalations that are merely rate-limited.
