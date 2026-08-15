---
id: 0358
topic: architecture
source_issue: 11242
source_phase: plan
created_at: 2026-08-15T10:14:37.592586+00:00
status: active
corroborations: 1
---

# No replace("|", "\\|") outside shared md_table_cell() in src/

The pipe-escaping pattern was duplicated across `src/escape/report.py`, `src/verification.py` (L40–41), `src/verification_judge.py` (L492), and `src/arch/generators/ai_system_inventory.py` (`_fmt_cell`). All four must call the public `md_table_cell()` in `src/markdown_cell.py` — no underscore prefix (cross-module import gotcha). The escaper is scoped to free-text cells only; backticked columns like `detection_ref` and `encoded_as` must not be passed through it.

**Why:** Concept-scatter means the same escaping bug recurs independently; a single shared escaper fixes it once and makes drift visible.
