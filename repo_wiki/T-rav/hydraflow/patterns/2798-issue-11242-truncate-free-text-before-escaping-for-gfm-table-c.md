---
id: 2798
topic: patterns
source_issue: 11242
source_phase: plan
created_at: 2026-08-15T10:14:37.592596+00:00
status: active
corroborations: 1
---

# Truncate free-text before escaping for GFM table cells (#11185)

In `src/escape/report.py`, evidence-cell truncation must happen before escaping, per #11185. The `md_table_cell()` escaper assumes its input is already truncated. Reversing the order truncates escaped sequences mid-way (e.g., `\|` → `\\|` then cut at `\\`), producing malformed cells that lose columns.

**Why:** Truncating after escaping can split an escape sequence, corrupting the rendered cell and breaking the 9-cell invariant.
