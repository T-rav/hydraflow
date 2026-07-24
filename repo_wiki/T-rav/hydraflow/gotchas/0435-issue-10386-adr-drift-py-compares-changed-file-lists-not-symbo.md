---
id: 0435
topic: gotchas
source_issue: 10386
source_phase: plan
created_at: 2026-07-24T04:38:03.777853+00:00
status: active
corroborations: 1
---

# adr_drift.py compares changed-file lists, not symbol evidence, per diff

`src/adr_drift.py`'s `compute_drift`/`_citation_drifts` logic determines drift from `gh`'s file-level PR diff — it has no way to see which symbols within a file actually changed. A bare-file ADR citation therefore drifts on *any* touch to that file, even unrelated ones.

**Why:** explains why symbol-qualified citations (`file.py:symbol`) behave differently under drift detection than bare-file citations — a gotcha to check before adding or editing ADR citation blocks in `docs/adr/`.
