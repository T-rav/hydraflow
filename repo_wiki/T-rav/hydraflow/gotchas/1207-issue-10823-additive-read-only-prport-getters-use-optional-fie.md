---
id: 1207
topic: gotchas
source_issue: 10823
source_phase: plan
created_at: 2026-07-31T00:48:51.333131+00:00
status: active
corroborations: 1
---

# Additive read-only PRPort getters use optional fields for shape compat

Add new `PRPort` getters as read-only methods with optional fields (default `None`) to keep old gh shapes compatible.

- `src/contracts/shapes.py`: `created_at` aliased `createdAt`, `default None`.
- `src/models.py`: `GitHubIssueSummary.created_at: NotRequired[str]`.
- `src/mockworld/fakes/fake_github.py` mirrors with a defensive copy.

**Why:** Existing shape consumers break on required fields they don't populate; optionality preserves backward compatibility across `PRPort` implementations.
