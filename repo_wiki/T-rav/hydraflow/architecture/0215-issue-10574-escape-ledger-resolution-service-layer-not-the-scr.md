---
id: 0215
topic: architecture
source_issue: 10574
source_phase: plan
created_at: 2026-07-26T00:21:42.291339+00:00
status: active
corroborations: 1
---

# Escape ledger resolution: service layer, not the script (src/escape/resolve.py)

Put validation and mutation logic in `src/escape/resolve.py` as pure functions (`resolve_escape`, `unresolved`, `default_ledger_path`); keep `scripts/resolve_escape.py` a thin argparse wrapper. `EscapeLedger.append_resolution` (src/escape/ledger.py) already existed unit-tested but had no caller — the gap was a service, not the ledger itself.

**Why:** keeps the resolution logic reusable by a future dashboard action without rewriting it out of a CLI script.
