---
id: 2302
topic: patterns
source_issue: 11185
source_phase: plan
created_at: 2026-08-14T23:55:43.383173+00:00
status: active
corroborations: 1
---

# Markdown table column changes update all row types together

When adding a column to a markdown table renderer in `src/escape/report.py`, update the header, separator, every data-row f-string, AND the empty-state placeholder row in the same commit.

- The "Recent escapes" table (lines 106-123) moved 8 → 9 cells across all four row types.
- The rollup table (lines 87-103) is a separate 3-cell table — do not touch it.

**Why:** Mismatched cell counts between header and data/placeholder rows silently break table rendering in GitHub Pages and terminals.
