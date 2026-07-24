---
id: 0162
topic: architecture
source_issue: 10384
source_phase: plan
created_at: 2026-07-24T04:55:51.365313+00:00
status: active
corroborations: 1
---

# Don't add a file to _SHARED_INFRA_MODULES to silence ADR drift — check ownership first

`_SHARED_INFRA_MODULES` in `src/adr_drift.py` is reserved for pure dependency-pointer modules with no owned symbols; adding a file there to stop a drift false-positive is over-broad if the ADR actually owns specific methods in that file. When an ADR genuinely owns symbols (e.g. ADR-0019 owning `EpicManager.release_epic`, `EpicCompletionChecker.check_and_close_epics`, `EpicManager.on_child_completed` in `src/epic.py`), fix the citation granularity instead, not the module suppression list.

**Why:** keeps drift detection meaningful — suppressing at module level would hide future genuine ADR-0019 violations in `src/epic.py`.
