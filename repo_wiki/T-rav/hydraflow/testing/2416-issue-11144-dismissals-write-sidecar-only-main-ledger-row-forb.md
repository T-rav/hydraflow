---
id: 2416
topic: testing
source_issue: 11144
source_phase: plan
created_at: 2026-08-14T14:39:13.298180+00:00
status: active
corroborations: 1
---

# Dismissals write sidecar only; main ledger row forbidden

ADR-0115 §Rejected forbids writing a main ledger row on dismissal. The sidecar `EscapeDiagnosisLedger` is authoritative for terminal verdicts.

- `test_dismissal_must_not_inflate_the_confirmed_escape_count` pins this invariant.
- A dismissed escape's ledger row stays untouched and `is_confirmed()` stays False.

**Why:** Writing a ledger row on dismissal inflates the confirmed-escape count and breaks the accounting model.
