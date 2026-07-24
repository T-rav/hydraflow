---
id: 0576
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.217517+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# adr_drift.py compares changed-file lists, not symbol evidence, per diff

`src/adr_drift.py`'s `compute_drift`/`_citation_drifts` logic determines drift from `gh`'s file-level PR diff — it has no way to see which symbols within a file actually changed. A bare-file ADR citation therefore drifts on any touch to that file, even unrelated ones.

**Why:** Explains why symbol-qualified citations (`file.py:symbol`) behave differently under drift detection than bare-file citations — a gotcha to check before adding or editing ADR citation blocks in `docs/adr/`.
