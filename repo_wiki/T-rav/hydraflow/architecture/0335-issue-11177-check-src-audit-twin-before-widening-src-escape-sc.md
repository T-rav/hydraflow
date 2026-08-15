---
id: 0335
topic: architecture
source_issue: 11177
source_phase: plan
created_at: 2026-08-14T22:44:18.538105+00:00
status: active
corroborations: 1
---

# Check src/audit twin before widening src/escape scope

Before widening the scope of changes in `src/escape/*`, check the mirrored `src/audit/*` module for twin logic that needs updating. When fixing `EscapeAutoDiagnoser._gather` in `src/escape/auto_diagnose.py`, verify if a corresponding diagnoser exists in `src/audit/`.

**Why:** Failing to update twin modules causes silent drift between the escape and audit pipelines.
