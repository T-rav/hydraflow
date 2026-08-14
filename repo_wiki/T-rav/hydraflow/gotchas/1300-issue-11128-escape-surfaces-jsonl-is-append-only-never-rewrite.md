---
id: 1300
topic: gotchas
source_issue: 11128
source_phase: plan
created_at: 2026-08-14T12:04:30.040463+00:00
status: active
corroborations: 1
---

# Escape surfaces JSONL is append-only — never rewrite or delete

Lines in `.hydraflow/diagnostics/escape_surfaces.jsonl` must never be mutated after write. New resolutions append; they do not edit existing surfacing links.

When closing stranded issues, the stranded-surfacing pass records ledger resolutions and lets `_reconcile_surfaced_issues` comment + close — it does not touch the original JSONL rows.

**Why:** Rewriting spent links would lose audit history and break idempotency assumptions shared by `src/escape_ledger_loop.py` and its 5+ regression pins.
