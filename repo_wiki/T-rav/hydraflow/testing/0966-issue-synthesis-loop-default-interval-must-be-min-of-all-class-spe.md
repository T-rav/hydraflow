---
id: 0966
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:21:18.091388+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952
---

# Loop default interval must be min() of all class-specific floors

`_get_default_interval` in `src/triage_retry_loop.py` must return `min(triage_retry_interval, triage_infra_retry_interval)`, not just the original 24h value.

Example: adding a shorter per-class retry floor without tightening the loop's own tick cadence leaves that floor dead code.

**Why:** if the loop's polling interval stays slower than a newly-added short floor, the loop never wakes up in time to act on it.
