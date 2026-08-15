---
id: 2183
topic: patterns
source_issue: 11178
source_phase: plan
created_at: 2026-08-14T23:03:00.703651+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Escape ledger is append-only — never backfill resolved rows

When fixing resolution metadata (e.g., replacing a `<detecting-commit-regression-pin>` placeholder with real paths), write new rows via `resolve_escape` only. Do not rewrite or backfill already-resolved rows.

- Rows resolved before the fix keep the placeholder permanently.
- The aging close comment quotes the *recorded* resolution, not a re-derived one.

**Why:** The ledger is an append-only event log; rewriting history breaks downstream audit assumptions.
