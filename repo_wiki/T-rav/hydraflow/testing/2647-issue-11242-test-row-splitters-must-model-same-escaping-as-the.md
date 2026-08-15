---
id: 2647
topic: testing
source_issue: 11242
source_phase: plan
created_at: 2026-08-15T10:14:37.592573+00:00
status: active
corroborations: 1
---

# Test row-splitters must model same escaping as the renderer they test

The `_table_cells` helper in `tests/test_escape_ledger.py` treated the second `\` of `\\|` as an escape, masking the exact bug it was supposed to catch — 9 unit tests plus a scenario shipped green over a column-dropping defect. When writing test row-splitters for GFM tables, model `\` as escaping whatever follows, matching the renderer's semantics, and add a self-test pin for the blind spot.

**Why:** A test helper with divergent escaping logic creates unfalsifiable pins that pass pre-fix and protect the bug.
