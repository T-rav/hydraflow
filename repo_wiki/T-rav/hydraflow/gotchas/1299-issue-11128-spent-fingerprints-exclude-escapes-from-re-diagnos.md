---
id: 1299
topic: gotchas
source_issue: 11128
source_phase: plan
created_at: 2026-08-14T12:04:30.040421+00:00
status: active
corroborations: 1
---

# Spent fingerprints exclude escapes from re-diagnosis

Once an escape's fingerprints have open surfacing links in `.hydraflow/diagnostics/escape_surfaces.jsonl`, `select_findings_to_surface` never returns them — so `_auto_diagnose` in `src/escape/auto_diagnose.py` cannot see them again, even when the detecting commit has since added a regression pin.

This means already-filed HITL issues age forever unless a separate pass walks OPEN links directly.

**Why:** Without a stranded-surfacing pass, a mechanically self-answering escape (e.g. `bug-issue:ec53c5c6…` whose commit added `tests/regressions/…`) stays paged even though `classify_diagnosis` would return `RESOLVED_ENCODED`.
