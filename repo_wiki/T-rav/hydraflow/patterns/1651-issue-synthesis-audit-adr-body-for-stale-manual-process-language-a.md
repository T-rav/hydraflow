---
id: 1651
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T11:12:29.291792+00:00
status: active
corroborations: 1
supersedes: 1557
---

# Audit ADR body for stale manual-process language after enforced header

When an ADR gains an `enforced` header because a trigger fired, audit its Decision body and Operational-impact sections for stale manual-process language.

Example: ADR-0027 Rule 2 (manual grep) and the Operational-impact section still read as pre-automation after the header was added, contradicting Rule 5 which retires Rule 2 entirely.

**Why:** A self-contradicting ADR misleads contributors into following retired manual processes instead of the automated check.
