---
id: 0309
topic: dependencies
source_issue: 11803
source_phase: plan
created_at: 2026-08-30T09:12:38.105423+00:00
status: active
corroborations: 1
---

# Place flow-runtime conventions in src/flows/, not phase modules

When deduplicating a helper used across multiple phases, place it in `src/flows/` rather than a phase-specific module.

`src/plan_phase_common.py` is a plan-package module imported by no other phase; routing implement/review through it adds a wrong dependency edge. `src/flows/` is a safe leaf (`flow.py` stdlib-only, `adapters.py` → L1 `file_util`), and all five consumer sites already import from `flows`.

**Why:** Importing across phase packages creates unexpected dependency edges and potential import cycles.
