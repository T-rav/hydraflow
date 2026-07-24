---
id: 0525
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.793877+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# adr_drift.py compares changed-file lists, not symbol evidence, per diff

`src/adr_drift.py`'s `compute_drift`/`_citation_drifts` logic determines drift from `gh`'s file-level PR diff — it has no way to see which symbols within a file actually changed. A bare-file ADR citation therefore drifts on any touch to that file, even unrelated ones.

**Why:** Explains why symbol-qualified citations (`file.py:symbol`) behave differently under drift detection than bare-file citations — a gotcha to check before adding or editing ADR citation blocks in `docs/adr/`.
