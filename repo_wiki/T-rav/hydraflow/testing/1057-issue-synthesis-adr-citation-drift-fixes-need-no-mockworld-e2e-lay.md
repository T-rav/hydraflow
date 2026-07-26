---
id: 1057
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.533077+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# ADR-citation drift fixes need no MockWorld/e2e layer — pure static check

For issue #10440 (fixing dead ADR source citations + adding a parser ratchet), the plan explicitly skips the MockWorld scenario and sandbox e2e test layers despite the repo's usual three-layer pyramid requirement (docs/standards/testing/README.md).

Example: the change is pure ADR-text plus a static test over a side-effect-free regex parser (_SOURCE_FILE_CITATION_RE) — it crosses no pipeline phase, runner, or Port.

**Why:** load-bearing-feature test-pyramid rules apply to features that touch runtime behavior; a text/static-analysis-only fix has no runtime surface for MockWorld or e2e to exercise, so skipping those layers isn't a shortcut here.
