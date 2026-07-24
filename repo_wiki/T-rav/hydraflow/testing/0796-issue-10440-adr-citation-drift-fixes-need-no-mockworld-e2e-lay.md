---
id: 0796
topic: testing
source_issue: 10440
source_phase: plan
created_at: 2026-07-24T10:50:57.616765+00:00
status: superseded
corroborations: 1
superseded_by: 0798
---

# ADR-citation drift fixes need no MockWorld/e2e layer — pure static check

For issue #10440 (fixing dead ADR source citations + adding a parser ratchet), the plan explicitly skips the MockWorld scenario and sandbox e2e test layers despite the repo's usual three-layer pyramid requirement (`docs/standards/testing/README.md`). Justification: the change is pure ADR-text plus a static test over a side-effect-free regex parser (`_SOURCE_FILE_CITATION_RE`) — it crosses no pipeline phase, runner, or Port.
**Why:** load-bearing-feature test-pyramid rules apply to features that touch runtime behavior; a text/static-analysis-only fix has no runtime surface for MockWorld or e2e to exercise, so skipping those layers isn't a shortcut here.
