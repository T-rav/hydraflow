---
id: 0435
topic: architecture
source_issue: 11869
source_phase: plan
created_at: 2026-09-01T05:42:49.576678+00:00
status: active
corroborations: 1
---

# Widen purity-pin imports when policy modules gain vocabulary helpers

When `src/charter_model.py` or other policy modules gain new imports from `src/data_class_vocabulary.py`, update the named import pins in `tests/architecture/test_policy_engine_is_pure.py` in the same step.

Example: `charter_model` importing `is_regulated_class` must be added to the purity pin list or the architecture gate fails.

**Why:** The purity gate is a white-list; an unlisted but functionally pure import still fails the gate, blocking the build.
