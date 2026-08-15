---
id: 0189
topic: dependencies
source_issue: 11241
source_phase: plan
created_at: 2026-08-15T10:09:34.777759+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Two-mode Markdown sanitizer: cell escapes pipes, prose does not

Use `sanitize_notes_cell()` for Markdown table cells (escape `|` → `\|`) and `sanitize_notes_prose()` for prose blocks (collapse whitespace + truncate, but do NOT escape `|` — it renders as a literal backslash). Both modes collapse newlines/tabs to a single line and truncate at `EVIDENCE_MAX_CHARS` before escaping so no `\|` pair is split.

**Why:** Pipe-escaping in prose context corrupts readability; skipping it in cell context breaks the evidence table to multiple columns.
