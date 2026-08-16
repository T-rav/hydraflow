---
id: 3466
topic: patterns
source_issue: 11314
source_phase: plan
created_at: 2026-08-16T07:29:20.234670+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Verify operator semantics before classifying default threshold bugs

Do not assume all threshold-adjacent defaults are bugs. `_triage_hints`' `(10, False)` default is safe because `_should_discover_helper` uses `<` (strictly less than), putting it on the documented "no helper" side. Leave it alone when fixing `>` boundary collisions.

**Why:** Blindly refactoring all boundary defaults introduces regressions. Operator semantics (`<` vs `>`) dictate whether a boundary value triggers the expected behavior or bypasses it.
