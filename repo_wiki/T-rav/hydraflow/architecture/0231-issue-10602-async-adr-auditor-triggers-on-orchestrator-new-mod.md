---
id: 0231
topic: architecture
source_issue: 10602
source_phase: plan
created_at: 2026-07-26T10:26:40.201301+00:00
status: active
corroborations: 1
---

# Async ADR auditor triggers on orchestrator + new modules

Modifying `src/orchestrator.py` while adding a new `src/*.py` module triggers the repo's async ADR touchpoint auditor. Add `Skip-ADR:` if the changes are implementation-level, or file an ADR if the detection-mechanism swap is architectural. **Why:** Prevents CI pipeline failures when altering core async dispatch logic.
