---
id: 0295
topic: architecture
source_issue: 10915
source_phase: plan
created_at: 2026-07-31T15:36:39.647855+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Register new instrument paths in _SELF_MOD_SUBSTRINGS

Add any new sensor/instrument directory to `judge_independence._SELF_MOD_SUBSTRINGS` so diffs touching it classify as `SELF_MODIFICATION` blast-radius and fail closed.

- Example: `"src/setpoint/"` added alongside existing entries.
- A diff touching the registered path must produce the self-modification class, not an independent verdict.

**Why:** Without registration, a self-modifying change to an instrument can receive an independent verdict, bypassing the very guard the instrument enforces.
