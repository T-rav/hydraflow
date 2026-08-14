---
id: 1328
topic: gotchas
source_issue: 11163
source_phase: plan
created_at: 2026-08-14T18:57:58.285583+00:00
status: active
corroborations: 1
---

# EscapeDiagnosisLedger readers must share one parse, not row-presence

All public sidecar readers in `src/escape/auto_diagnose.py` — `terminal_ids()`, `verdict_for()`, `dismissal_reasons()` — must derive from one private last-row-wins parsed map. Never let one reader check row presence while another parses the `diagnosis` field.

- Bug: `terminal_ids()` was `set(existing_ids())` (presence), `verdict_for()` parsed to `EscapeDiagnosis` mapping unknown→`None`.
- Fix: one shared map; `terminal_ids()` = ids whose latest row parses to `RESOLVED_ENCODED`/`DISMISSED`.

**Why:** Divergent readers silently retire escapes when an unparseable row passes the gate before `diagnose()` can re-classify it.
