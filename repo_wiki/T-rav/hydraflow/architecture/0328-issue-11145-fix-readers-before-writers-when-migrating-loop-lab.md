---
id: 0328
topic: architecture
source_issue: 11145
source_phase: plan
created_at: 2026-08-14T15:10:07.166473+00:00
status: active
corroborations: 1
---

# Fix readers before writers when migrating loop label semantics

When changing what label caretaker loops file under, land reader changes (P2/P3) before writer changes (P4). Readers must poll the union of old and new labels first; only then flip writers to the new root.

- Violating this order strands every caretaker escalation — writers file the new label, readers don't see it yet.
- This is a silent factory-wide HITL outage, not a test failure.

**Why:** Escalations from 14 writer modules (`staging_bisect_loop.py`, `diagnostic_loop.py`, etc.) become invisible to `auto_agent_preflight_loop` and `detector_calibration_loop` if writers flip before readers poll the union.
