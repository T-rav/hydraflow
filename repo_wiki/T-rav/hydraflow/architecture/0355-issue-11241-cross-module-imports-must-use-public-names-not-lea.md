---
id: 0355
topic: architecture
source_issue: 11241
source_phase: plan
created_at: 2026-08-15T10:09:34.777736+00:00
status: active
corroborations: 1
---

# Cross-module imports must use public names, not leading-underscore

When promoting a private helper like `report.py::_sanitize_evidence_cell` into a shared module (`src/escape/notes.py`), expose it as a public function (`sanitize_notes_cell()`) and import the public name. Do not import `_sanitize_evidence_cell` across module boundaries.

**Why:** Cross-module `_` imports are a documented gotcha in this repo — private names signal module-local intent and break encapsulation silently when refactored.
