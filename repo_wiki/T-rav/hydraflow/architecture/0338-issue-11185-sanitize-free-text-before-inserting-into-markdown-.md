---
id: 0338
topic: architecture
source_issue: 11185
source_phase: plan
created_at: 2026-08-14T23:55:43.383203+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Sanitize free-text before inserting into markdown table cells

Pipe any free-text field through a private cell sanitizer before inserting it into a markdown table cell. The sanitizer must: escape `|`, collapse newlines to spaces, truncate to a module constant with `…`, and render `—` when empty.

- `EscapeRecord.notes` is written by `escape.detect`, `escape.resolve.resolve_escape`, and `escape.auto_diagnose` — all produce prose, paths, or multi-line text.

**Why:** A single `|` or newline in `notes` splits a table row into extra cells, corrupting the entire table layout.
