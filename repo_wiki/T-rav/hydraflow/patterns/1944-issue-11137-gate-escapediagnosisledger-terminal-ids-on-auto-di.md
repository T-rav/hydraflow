---
id: 1944
topic: patterns
source_issue: 11137
source_phase: plan
created_at: 2026-08-14T13:57:19.247688+00:00
status: superseded
corroborations: 1
superseded_by: 2052
---

# Gate EscapeDiagnosisLedger.terminal_ids() on auto-diagnose config

When sourcing terminal ids from `EscapeDiagnosisLedger(self._diagnoses_path).terminal_ids()` in `_surface_findings`, pass an empty set when `escape_ledger_auto_diagnose_enabled` is off.
- Config-on: real terminal ids flow to the selector.
- Config-off: empty set → selector behaves identically to today.
**Why:** Reading the sidecar unconditionally would silently suppress human surfaces in the diagnoser-disabled build, because historical terminal verdicts would be treated as active exclusions.
