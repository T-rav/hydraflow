---
id: 2596
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:52.063622+00:00
status: active
corroborations: 1
supersedes: 2416
---

# Dismissals write sidecar only; main ledger row forbidden

ADR-0115 §Rejected forbids writing a main ledger row on dismissal. The sidecar `EscapeDiagnosisLedger` is authoritative for terminal verdicts.

Example: `test_dismissal_must_not_inflate_the_confirmed_escape_count` pins this invariant. A dismissed escape's ledger row stays untouched and `is_confirmed()` stays False.

**Why:** Writing a ledger row on dismissal inflates the confirmed-escape count and breaks the accounting model.
