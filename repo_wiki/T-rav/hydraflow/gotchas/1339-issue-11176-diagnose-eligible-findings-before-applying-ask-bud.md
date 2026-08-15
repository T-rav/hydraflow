---
id: 1339
topic: gotchas
source_issue: 11176
source_phase: plan
created_at: 2026-08-14T22:35:54.596936+00:00
status: active
corroborations: 1
---

# Diagnose eligible findings before applying ask budget in escape ledger

Rule: In `escape_ledger_loop.py`, separate uncapped eligibility (`eligible_findings`) from budget application (`apply_ask_budget`) so `_auto_diagnose` sees the full list before any truncation.

- Old `select_findings_to_surface` truncated to `escape_ledger_max_issues_per_tick` *before* diagnosis ran, so capped findings burned ask slots with no backfill.
- Fix: diagnose the eligible list in order, then spend the ask budget on the INCONCLUSIVE residue only.

**Why:** Truncating before diagnosis starves genuine escapes that sit behind self-resolvable rows — they never get machine-examined and waste human-ask budget.
