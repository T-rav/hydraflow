---
id: 0940
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.980357+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0953
---

# ADR-citation drift fixes need no MockWorld/e2e layer — pure static check

For issue #10440 (fixing dead ADR source citations + adding a parser ratchet), the plan explicitly skips the MockWorld scenario and sandbox e2e test layers despite the repo's usual three-layer pyramid requirement (`docs/standards/testing/README.md`). Justification: the change is pure ADR-text plus a static test over a side-effect-free regex parser (`_SOURCE_FILE_CITATION_RE`) — it crosses no pipeline phase, runner, or Port.

**Why:** load-bearing-feature test-pyramid rules apply to features that touch runtime behavior; a text/static-analysis-only fix has no runtime surface for MockWorld or e2e to exercise, so skipping those layers isn't a shortcut here.
