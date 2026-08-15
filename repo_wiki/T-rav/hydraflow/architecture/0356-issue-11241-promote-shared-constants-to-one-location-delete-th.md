---
id: 0356
topic: architecture
source_issue: 11241
source_phase: plan
created_at: 2026-08-15T10:09:34.777749+00:00
status: active
corroborations: 1
---

# Promote shared constants to one location; delete the original

When moving logic to a new module (e.g. `_sanitize_evidence_cell` → `src/escape/notes.py`), the associated constant (`EVIDENCE_MAX_CHARS`) must live in exactly one place. Delete the copy left behind in `report.py`. Precedent: the `LEDGER_FILENAME` promotion fixed the same concept-scatter smell.

**Why:** Leaving a duplicate constant behind causes the two copies to drift, silently changing truncation behavior depending on which call site is used.
