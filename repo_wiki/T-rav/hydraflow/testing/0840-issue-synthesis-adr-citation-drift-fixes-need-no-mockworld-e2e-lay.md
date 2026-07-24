---
id: 0840
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.221144+00:00
status: active
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
---

# ADR-citation drift fixes need no MockWorld/e2e layer — pure static check

For issue #10440 (fixing dead ADR source citations + adding a parser ratchet), the plan explicitly skips the MockWorld scenario and sandbox e2e test layers despite the repo's usual three-layer pyramid requirement (`docs/standards/testing/README.md`). Justification: the change is pure ADR-text plus a static test over a side-effect-free regex parser (`_SOURCE_FILE_CITATION_RE`) — it crosses no pipeline phase, runner, or Port.

**Why:** load-bearing-feature test-pyramid rules apply to features that touch runtime behavior; a text/static-analysis-only fix has no runtime surface for MockWorld or e2e to exercise, so skipping those layers isn't a shortcut here.
