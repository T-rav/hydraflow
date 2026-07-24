---
id: 0477
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.399725+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0494
---

# adr_drift.py compares changed-file lists, not symbol evidence, per diff

`src/adr_drift.py`'s `compute_drift`/`_citation_drifts` logic determines drift from `gh`'s file-level PR diff — it has no way to see which symbols within a file actually changed. A bare-file ADR citation therefore drifts on *any* touch to that file, even unrelated ones.

**Why:** explains why symbol-qualified citations (`file.py:symbol`) behave differently under drift detection than bare-file citations — a gotcha to check before adding or editing ADR citation blocks in `docs/adr/`.
