---
id: 0340
topic: architecture
source_issue: 11185
source_phase: plan
created_at: 2026-08-14T23:55:43.383230+00:00
status: active
corroborations: 1
---

# Prefer render-only changes to avoid schema migration

When the goal is surfacing existing data in a human-facing report, modify only the renderer — not the schema, writer, or consumers.

- `EscapeRecord.notes` already carries the artifact encoding; `escape_ledger_loop._render_finding` already emits it. Only `src/escape/report.py` dropped it.
- No changes to `EscapeRecord`, `escape_ledger.jsonl` layout, or the `encoded_as` rollup table.

**Why:** Schema and writer changes require migration, break backward compatibility, and ripple across consumers — a render-only fix is safe and reversible.
