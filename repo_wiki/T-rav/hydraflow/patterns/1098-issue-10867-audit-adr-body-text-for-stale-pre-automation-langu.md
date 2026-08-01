---
id: 1098
topic: patterns
source_issue: 10867
source_phase: review
created_at: 2026-07-31T10:45:43.194353+00:00
status: superseded
corroborations: 1
superseded_by: 1472
---

# Audit ADR body text for stale pre-automation language after adding enforced header

When an ADR gains an `enforced` header because a trigger fired, audit the Decision body and Operational-impact sections for stale manual-process language. In ADR-0027, Rule 2 (manual grep) and the Operational-impact section still read as pre-automation after the header was added, contradicting Rule 5 which retires Rule 2 entirely once the trigger deadline passes.

**Why:** A self-contradicting ADR misleads contributors into following retired manual processes instead of the automated check.
