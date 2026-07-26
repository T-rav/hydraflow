---
id: 0838
topic: gotchas
source_issue: 10503
source_phase: plan
created_at: 2026-07-25T02:16:20.035300+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# Scope EscapeLedgerLoop surfacing dedup keys per reason, not per record

A single `surfaced:<id>` key in `src/escape_ledger_loop.py` conflates independent surfacing criteria (low-confidence attribution vs. unencoded aging past `escape_ledger_encoding_age_days`) — spending the key on the first-fired reason silently suppresses the other forever. Fix: key as `surfaced:<reason>:<id>` with named constants (e.g. `REASON_LOW_CONFIDENCE`, `REASON_AGING`), and have `select_findings_to_surface` return `(record, reasons)` pairs listing only unspent criteria. A record eligible under both reasons at once files one issue naming both and spends both keys.

**Why:** Without reason-scoping, the 14-day aging surface in `select_findings_to_surface` is dead code — any record already surfaced once for a different reason can never re-fire.
