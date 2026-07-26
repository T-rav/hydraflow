---
id: 1040
topic: gotchas
source_issue: 10577
source_phase: plan
created_at: 2026-07-26T01:40:01.589327+00:00
status: active
corroborations: 1
---

# Link stores must live outside DedupStore — it only holds strings

`DedupStore` in `src/escape_ledger_loop.py` is a set of fingerprint strings; it cannot carry a mapping like fingerprint→issue number. To persist a value alongside a fingerprint (e.g. the GitHub issue number `create_issue` returns), add a separate append-only JSONL sidecar store — e.g. `src/escape/surfaces.py`'s `SurfacedIssueLedger` under `<data_root>/diagnostics` — rather than trying to encode the value into the dedup fingerprint itself (which would break exact-match dedup in `select_findings_to_surface`).

**Why:** conflating dedup state with payload data silently breaks the reason-scoped one-shot dedup budget from #10503.
