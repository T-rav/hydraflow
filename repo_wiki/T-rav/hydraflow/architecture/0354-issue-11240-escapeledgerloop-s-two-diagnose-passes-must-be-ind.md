---
id: 0354
topic: architecture
source_issue: 11240
source_phase: plan
created_at: 2026-08-15T09:55:52.986928+00:00
status: active
corroborations: 1
---

# EscapeLedgerLoop's two diagnose passes must be independently bounded

Do not thread a shared tick budget through `_do_work` for `EscapeLedgerLoop`'s two diagnose passes (`_surface_findings` and `_diagnose_open_links`). Each pass gets its own `escape_ledger_max_diagnoses_per_tick` budget applied per-pass.
- `_reconcile_surfaced_issues` (which drives `_diagnose_open_links`) runs first and unconditionally; `_surface_findings` is skipped on quiet ticks. A shared budget lets reconcile drain it before the sibling pass.

**Why:** Starving `_surface_findings` reintroduces #11176 one layer out — new findings never surface while the open-link backlog consumes all budget.
