---
id: 1283
topic: gotchas
source_issue: 11111
source_phase: plan
created_at: 2026-08-14T09:08:28.015682+00:00
status: active
corroborations: 1
---

# Sidecar JSONL is append-only, last-row-wins, fail-open on malformed rows

The escape diagnosis sidecar (`DIAGNOSES_FILENAME`, exported from `src/escape/auto_diagnose.py`) is append-only; never rewrite rows. Parse with last-row-wins semantics and treat unrecognized diagnosis strings as non-terminal.

- `terminal_verdicts()` keeps only the last row per escape id
- Malformed rows → no verdict → non-terminal → re-diagnosed (fail-open)

**Why:** Rewrite-free append-only preserves audit history; fail-open matches pre-change behavior and prevents a bad row from permanently blocking re-diagnosis.
