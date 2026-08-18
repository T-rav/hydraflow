---
id: 1474
topic: gotchas
source_issue: 11407
source_phase: plan
created_at: 2026-08-18T02:53:10.561516+00:00
status: active
corroborations: 1
---

# Class titles are stable-by-design: multiple sites share one title

In `src/find_class_key.py`, class titles are never reworded per site. Issue #11328 exists precisely because the same title can appear for distinct sites (e.g., `src/foo.py:12` and `src/bar.py:99`). This is the normal path, not an exotic edge case.

When designing roster logic, assume title collision across sites is expected and must be resolved by site identifier, not by title uniqueness.

**Why:** Treating title uniqueness as invariant causes silent site drops when two distinct sites share a class title.
