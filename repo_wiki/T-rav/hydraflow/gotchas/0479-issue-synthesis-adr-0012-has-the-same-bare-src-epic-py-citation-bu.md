---
id: 0479
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.401047+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0494
---

# ADR-0012 has the same bare src/epic.py citation bug — separate issue, don't bundle

ADR-0012 cites `` `src/epic.py` `` bare, same as ADR-0019 did before #10384's fix — but fixing it there won't close #10384 and is out of scope for that PR. File a separate issue for ADR-0012's citation fix rather than bundling it into an unrelated rollup-closing PR.

**Why:** keeps PRs scoped to the rollup they're meant to close; bundling unrelated ADR fixes risks scope creep per `docs/wiki/architecture-refactoring.md` multi-PR drift discipline.
