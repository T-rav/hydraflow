---
id: 1557
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T07:44:04.540468+00:00
status: superseded
corroborations: 1
supersedes: 1472
superseded_by: 1651
---

# Audit ADR body for stale manual-process language after enforced header

When an ADR gains an `enforced` header because a trigger fired, audit its Decision body and Operational-impact sections for stale manual-process language.

Example: ADR-0027 Rule 2 (manual grep) and the Operational-impact section still read as pre-automation after the header was added, contradicting Rule 5 which retires Rule 2 entirely.

**Why:** A self-contradicting ADR misleads contributors into following retired manual processes instead of the automated check.
