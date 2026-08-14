---
id: 1945
topic: patterns
source_issue: 11137
source_phase: plan
created_at: 2026-08-14T13:57:19.247696+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# dismissed verdict must stay non-mutating in EscapeDiagnosisLedger

A `dismissed` verdict from `_auto_diagnose` intentionally makes no `EscapeDiagnosisLedger` mutation. Selection or filtering fixes must not introduce writes for dismissals.
- `dismissed` rows stay in the ledger as-is; the pre-cap filter in `select_findings_to_surface` handles their exclusion at read time.
**Why:** Writing ledger rows for dismissals would break the backward-compat invariant that terminal verdicts are derived, not persisted, and would couple diagnoser output to ledger state.
