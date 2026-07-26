---
id: 0997
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.593108+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Doc-typo ADR fixes still need parser-consumer regression tests

For a citation-repoint fix on ADR-0049 (docs/adr/0049-trust-loop-kill-switch-convention.md), the regression test lives in tests/regressions/test_issue_10444.py and asserts against parse_adr_file() output — that source_files includes src/base_background_loop.py and src/bg_worker_manager.py, and source_symbols maps them to LoopDeps / BGWorkerManager.is_enabled respectively.

Example: classified as not-load-bearing (no pipeline/runner/loop change), so per docs/standards/testing/README.md it skips MockWorld scenario and sandbox e2e — unit-level parser assertions plus the static guard are sufficient.

**Why:** an ADR text edit with no test would let the citation format regress again with no CI signal, same as #9514/#10440.
