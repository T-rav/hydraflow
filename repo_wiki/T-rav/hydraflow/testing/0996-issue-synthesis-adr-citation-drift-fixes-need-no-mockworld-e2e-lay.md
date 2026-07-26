---
id: 0996
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.591866+00:00
status: superseded
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
superseded_by: 1015
---

# ADR-citation drift fixes need no MockWorld/e2e layer — pure static check

For issue #10440 (fixing dead ADR source citations + adding a parser ratchet), the plan explicitly skips the MockWorld scenario and sandbox e2e test layers despite the repo's usual three-layer pyramid requirement (docs/standards/testing/README.md).

Example: the change is pure ADR-text plus a static test over a side-effect-free regex parser (_SOURCE_FILE_CITATION_RE) — it crosses no pipeline phase, runner, or Port.

**Why:** load-bearing-feature test-pyramid rules apply to features that touch runtime behavior; a text/static-analysis-only fix has no runtime surface for MockWorld or e2e to exercise, so skipping those layers isn't a shortcut here.
