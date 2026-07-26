---
id: 0983
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.575385+00:00
status: superseded
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
superseded_by: 1015
---

# sandbox_main.py's SANDBOX_SEAMS registry needs a seam per subprocess loop

src/mockworld/sandbox_main.py holds an air-gap seam registry (SANDBOX_SEAMS) — every new subprocess-spawning loop must register a seam (config-disable, seed, or mockworld-sentinel) here.

Example: completeness is enforced by tests/architecture/test_sandbox_seam_completeness.py, not by the ADR citation itself.

**Why:** the seam-completeness test is the real PR-time enforcement of the air-gap invariant; ADR-0052 citations should point to it (via Enforced-by) rather than relying on drift detection over the registry file.
