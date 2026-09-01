---
id: 1544
topic: gotchas
source_issue: 11868
source_phase: plan
created_at: 2026-09-01T03:50:35.471946+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Test arch generators with synthetic Fact/Charter, no repo reads

Rule: Generator tests in `tests/architecture/` must construct synthetic `Fact` and `Charter` objects with no repo reads. Key assertions:

- Byte-identical output on re-render with identical inputs
- Output contains `{{ARCH_FOOTER}}` and no ISO timestamp
- Pipe characters in reason text are escaped to keep tables well-formed
- `DecisionEngineError` survivors: other standards' rows persist after one fails

**Why:** Synthetic inputs keep generator tests deterministic and isolate rendering logic from fact-collection and charter-loading concerns.
