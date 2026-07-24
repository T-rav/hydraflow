---
id: 0198
topic: architecture
source_issue: 10457
source_phase: plan
created_at: 2026-07-24T12:45:53.971852+00:00
status: active
corroborations: 1
---

# Rollup adr_numbers field defaults to [] for schema-evolution safety

`set_adr_rollup`/`get_adr_rollup`/`all_adr_rollups` in `src/state/_adr_audit.py` treat the member-ADR list as optional, defaulting to `[]` per ADR-0021. Fleet rollups filed before `adr_numbers` existed read back `adr_numbers == []` — no `KeyError`, but also ineligible for the fleet auto-close branch (empty list ⇒ not a fleet candidate). New filings from `src/adr_touchpoint_auditor_loop.py` populate it as `[e.adr.number for e in members]`; per-ADR rollups keep it `[]`.

**Why:** New auto-triage logic layers onto old rollup records without a migration, while old records correctly stay one-shot/human-closed.
