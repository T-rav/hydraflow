---
id: 1946
topic: patterns
source_issue: 11138
source_phase: plan
created_at: 2026-08-14T14:08:04.915441+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Hydraflow ledger notes are append-only; don't backfill HEAD: fixes

When `escape.auto_diagnose.regression_hits` was fixed to strip `HEAD:` prefixes, already-written ledger notes containing `HEAD:` stay as-is. The audit trail is append-only.

- New auto-resolved escapes get clean repo-relative paths in `notes`.
- Old rows keep their `HEAD:` notes forever; no migration, no compat shim.

**Why:** Backfilling immutable audit rows would rewrite history and break the append-only contract that downstream consumers (HITL close-comment path) rely on for traceability.
