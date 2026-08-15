---
id: 0357
topic: architecture
source_issue: 11242
source_phase: plan
created_at: 2026-08-15T10:14:37.592538+00:00
status: active
corroborations: 1
---

# GFM table cell escaping: backslash must be escaped before pipe

When escaping free-text for GFM table cells, escape `\` first, then `|`. The repo's own micromark parser (`src/ui/node_modules`) confirms: cell text `p\|q` renders `<td>p\</td>` — `q` is silently lost. Escaping backslash first (`p\\|q`) round-trips correctly. Route all free-text cells through `md_table_cell()` in `src/markdown_cell.py`.

**Why:** Escaping only `|` turns `\|` into `\\|`, which GFM reads as escaped-backslash + live delimiter, dropping everything after it.
