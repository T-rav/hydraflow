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

- Implement `title_token_overlap` / `CLASS_MARKER_TITLE_FLOOR`.
- Calibrate so `test_issue_11292.py`'s tightest real pair still passes — measured directly via `title_token_overlap` at 0.0714 (the ADR-pin family's 1st/3rd sibling titles), not the ≈0.20 this entry originally claimed. `CLASS_MARKER_TITLE_FLOOR = 0.05` leaves only ~1.4x headroom against that real pair.

**Why:** A single shared token is insufficient evidence of class membership; without a floor, unrelated issues sharing one common word false-fold together.
