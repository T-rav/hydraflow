---
id: 0579
topic: patterns
source_issue: 10577
source_phase: plan
created_at: 2026-07-26T01:40:01.589363+00:00
status: active
corroborations: 1
---

# Terminal-row convention for idempotent JSONL ledgers (last-row-wins)

For append-only JSONL stores in `src/escape/`, encode a terminal/closed state as a new row appended for the same key (e.g. fingerprint) rather than rewriting or deleting prior rows — readers take the last row per key as authoritative. `EscapeLedger.append_resolution` already follows this; `SurfacedIssueLedger` (src/escape/surfaces.py) reuses it so a 'closed' row makes closing one-shot across restarts without holding state only in memory.

**Why:** in-memory-only state gets lost on restart and causes the loop to re-comment/re-close every tick; `DedupStore.set_all` already rewrites its whole file, so nothing here may skip durability.
