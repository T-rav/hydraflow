---
id: 1447
topic: gotchas
source_issue: 11328
source_phase: review
created_at: 2026-08-16T12:27:43.693256+00:00
status: active
corroborations: 1
---

# match_class marker-equality path lacks title-affinity floor

Folding in `src/find_class_key.py:204-224` (`match_class`) must require both a needle backstop AND a title-affinity floor before classifying two issues as the same class. Currently the marker-equality path folds on any single shared needle token with title-or-body — the digest-collision false-fold hole the plan intended to close.

- Implement `class_title_affinity` / `CLASS_MARKER_TITLE_FLOOR`.
- Calibrate so `test_issue_11292.py`'s tightest real pair (≈0.20 affinity) still passes.

**Why:** A single shared token is insufficient evidence of class membership; without a floor, unrelated issues sharing one common word false-fold together.
