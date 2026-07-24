---
id: 0675
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.469876+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
superseded_by: 0704
---

# ADR-0012 has the same bare src/epic.py citation bug — file separately

ADR-0012 cites `src/epic.py` bare, same as ADR-0019 did before #10384's fix — but fixing it there won't close #10384 and is out of scope for that PR.

Example: file a separate issue for ADR-0012's citation fix rather than bundling it into an unrelated rollup-closing PR.

**Why:** Keeps PRs scoped to the rollup they're meant to close; bundling unrelated ADR fixes risks scope creep per `docs/wiki/architecture-refactoring.md` multi-PR drift discipline.
