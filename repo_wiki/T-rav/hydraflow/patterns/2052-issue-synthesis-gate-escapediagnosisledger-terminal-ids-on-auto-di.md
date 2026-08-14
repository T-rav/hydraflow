---
id: 2052
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T18:39:31.846737+00:00
status: active
corroborations: 1
supersedes: 1944
---

# Gate EscapeDiagnosisLedger.terminal_ids() on auto-diagnose config

When sourcing terminal ids from `EscapeDiagnosisLedger.terminal_ids()` in `_surface_findings`, pass an empty set when `escape_ledger_auto_diagnose_enabled` is off.

Example: Config-on → real terminal ids flow to the selector; config-off → empty set, selector behaves identically to today.

**Why:** Reading the sidecar unconditionally would silently suppress human surfaces in the diagnoser-disabled build, because historical terminal verdicts would be treated as active exclusions.
