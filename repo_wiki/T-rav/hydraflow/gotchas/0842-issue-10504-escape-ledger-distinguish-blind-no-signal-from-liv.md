---
id: 0842
topic: gotchas
source_issue: 10504
source_phase: plan
created_at: 2026-07-25T02:18:04.061438+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# Escape ledger: distinguish 'blind' (no signal) from 'live' (0 confirmed) gauges

A metric reading 0.00 is ambiguous between "gate is perfect" and "gate can't see anything." `escape/metrics.gauge_calibration()` resolves this for the confirmed-escape rate: status is `live` when ≥1 CONFIRMED row exists in the window, `blind` when all rows are low-confidence or the ledger is empty. `report.py`'s headline renders this status plus a high/medium/low confidence breakdown so `escape-ledger.md` falsifies gate quality instead of reporting a permanent, uninformative 0.00. **Why:** without a calibration signal, a broken detector (see the splitlines bug above) and a genuinely clean codebase are indistinguishable in the rendered report.
