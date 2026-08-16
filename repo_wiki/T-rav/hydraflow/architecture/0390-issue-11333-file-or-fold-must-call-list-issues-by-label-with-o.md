---
id: 0390
topic: architecture
source_issue: 11333
source_phase: plan
created_at: 2026-08-16T11:30:55.516386+00:00
status: active
corroborations: 1
---

# file_or_fold must call list_issues_by_label with one positional arg

Do not add `limit=` or `search=` kwargs to the `prs.list_issues_by_label(label)` call in `src/find_class_key.py`. The regression fixture's `_FoldPort` defines exactly that single-positional-arg signature; a kwarg raises `TypeError`.

- Window widening lives inside `PRManager`, not at the call site.
- The module docstring records the bounded-window contract instead of the signature changing.

**Why:** The fold decision's Port/adapter/fake three-layer mirror breaks if any layer's signature drifts from the fixture-pinned shape.
