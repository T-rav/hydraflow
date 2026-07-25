---
id: 0206
topic: architecture
source_issue: 10498
source_phase: review
created_at: 2026-07-25T09:07:23.395837+00:00
status: active
corroborations: 1
---

# EscapeRecord lacks a field to persist the closing-issue reference

`EscapeRecord` (backing `src/escape_ledger_loop.py`) has no field for the originating closing ref, so a computed `#N` closing-issue pointer is discarded after detection — HITL findings render `originating_pr`/`originating_merge_sha` as `—` with no attribution lead (`src/escape_ledger_loop.py:439`). This is a known-open schema gap, not yet fixed: adding a persisted field (e.g. `closes_ref`) requires design sign-off per the pre-flight escalation plan, so reviewers should flag rather than patch it in-flight.

**Why:** silently dropping computed attribution data defeats the purpose of the HITL finding and can't be fixed as a drive-by edit since it's a schema change.
