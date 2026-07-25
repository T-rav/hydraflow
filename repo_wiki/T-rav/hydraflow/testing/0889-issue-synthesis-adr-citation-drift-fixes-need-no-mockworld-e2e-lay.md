---
id: 0889
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.567249+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0897
---

# ADR-citation drift fixes need no MockWorld/e2e layer — pure static check

For issue #10440 (fixing dead ADR source citations + adding a parser ratchet), the plan explicitly skips the MockWorld scenario and sandbox e2e test layers despite the repo's usual three-layer pyramid requirement (`docs/standards/testing/README.md`). Justification: the change is pure ADR-text plus a static test over a side-effect-free regex parser (`_SOURCE_FILE_CITATION_RE`) — it crosses no pipeline phase, runner, or Port.

**Why:** load-bearing-feature test-pyramid rules apply to features that touch runtime behavior; a text/static-analysis-only fix has no runtime surface for MockWorld or e2e to exercise, so skipping those layers isn't a shortcut here.
