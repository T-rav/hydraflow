---
id: 0527
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.795386+00:00
status: superseded
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
superseded_by: 0545
---

# ADR-0012 has the same bare src/epic.py citation bug — file separately

ADR-0012 cites `src/epic.py` bare, same as ADR-0019 did before #10384's fix — but fixing it there won't close #10384 and is out of scope for that PR.

Example: file a separate issue for ADR-0012's citation fix rather than bundling it into an unrelated rollup-closing PR.

**Why:** Keeps PRs scoped to the rollup they're meant to close; bundling unrelated ADR fixes risks scope creep per `docs/wiki/architecture-refactoring.md` multi-PR drift discipline.
