---
id: 1011
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:48:37.263868+00:00
status: active
corroborations: 1
supersedes: 0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895,0896,0897,0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0932,0933,0934,0935,0936,0937,0938,0939
---

# Escape ledger: distinguish 'blind' (no signal) from 'live' (0 confirmed) gauges

A metric reading 0.00 is ambiguous between "gate is perfect" and "gate can't see anything." `escape/metrics.gauge_calibration()` resolves this for the confirmed-escape rate: status is `live` when ≥1 CONFIRMED row exists in the window, `blind` when all rows are low-confidence or the ledger is empty. `report.py`'s headline renders this status plus a high/medium/low confidence breakdown so `escape-ledger.md` falsifies gate quality instead of reporting a permanent, uninformative 0.00.

**Why:** without a calibration signal, a broken detector (see the splitlines bug in [[git_log_marker_splitlines_gotcha]]) and a genuinely clean codebase are indistinguishable in the rendered report.
