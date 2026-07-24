---
id: 0437
topic: gotchas
source_issue: 10384
source_phase: plan
created_at: 2026-07-24T04:55:51.365322+00:00
status: active
corroborations: 1
---

# ADR-0012 has the same bare src/epic.py citation bug — separate issue, don't bundle

ADR-0012 cites `` `src/epic.py` `` bare, same as ADR-0019 did before #10384's fix — but fixing it there won't close #10384 and is out of scope for that PR. File a separate issue for ADR-0012's citation fix rather than bundling it into an unrelated rollup-closing PR.

**Why:** keeps PRs scoped to the rollup they're meant to close; bundling unrelated ADR fixes risks scope creep per `docs/wiki/architecture-refactoring.md` multi-PR drift discipline.
