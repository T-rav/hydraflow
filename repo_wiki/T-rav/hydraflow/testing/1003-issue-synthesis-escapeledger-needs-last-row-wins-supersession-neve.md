---
id: 1003
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:21:18.156423+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952
---

# EscapeLedger needs last-row-wins supersession, never in-place rewrites

`EscapeLedger` (`src/escape/ledger.py`) is append-only. Reaching a terminal state (e.g. `encoded_as: detector` + `regression-test`) means appending a new row for the same id, never rewriting the original line.

Example: derived readers must collapse to the latest row per id: `src/escape/metrics.py` and `src/escape_ledger_loop.py`'s `_render_reports`/`_surface_findings` all need the same latest-per-id read; `existing_ids()` must still contain the id exactly once after supersession, so a re-tick doesn't re-record. Keep the change to one read helper + one append helper — a growing mutation API is scope creep.

**Why:** the ledger's append-only guarantee preserves audit-trail integrity; in-place rewrites would erase false-positive history.
