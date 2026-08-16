---
id: 1462
topic: gotchas
source_issue: 11344
source_phase: plan
created_at: 2026-08-16T13:29:50.590354+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Avoid markdown bold inside predicate-matched phrases in docstrings

Rule: Write `Does not mirror` (unbolded), not `Does **not** mirror`. Markdown bold splits regex patterns like `not mirror` that sibling-issue predicates scan for.

- `#11335`'s `_divergence_is_documented()` regex fails when `**` interrupts the matched phrase.
- `#11344` passes either way, but the unbolded form keeps sibling issues green.

**Why:** Docstring predicates operate on raw text, not rendered markdown; inline formatting breaks word-boundary matching.
