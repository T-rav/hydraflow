---
id: 3319
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:16:49.070526+00:00
status: superseded
corroborations: 1
supersedes: 3186
superseded_by: 3456
---

# Truncate free-text before escaping for GFM table cells (#11185)

In `src/escape/report.py`, evidence-cell truncation must happen before escaping, per #11185. The `md_table_cell()` escaper assumes its input is already truncated. Reversing the order truncates escaped sequences mid-way (e.g. `\|` → `\\|` then cut at `\\`), producing malformed cells that lose columns.

**Why:** Truncating after escaping can split an escape sequence, corrupting the rendered cell and breaking the 9-cell invariant.
