---
id: 0411
topic: architecture
source_issue: 11481
source_phase: plan
created_at: 2026-08-20T09:13:45.273087+00:00
status: active
corroborations: 1
---

# Import canonical regex from false_close, do not widen in place

When fixing narrowed closing-verb regexes, import canonical patterns from `src/false_close.py` instead of widening local regexes. Replace local `fixes_re` in `src/branch_gc_scan.py` and `src/pr_manager.py` with `CLOSE_KEYWORD_RE`.

**Why:** ADR-0037 enforces one canonical pattern to prevent invented variants and silent divergence across module boundaries.
