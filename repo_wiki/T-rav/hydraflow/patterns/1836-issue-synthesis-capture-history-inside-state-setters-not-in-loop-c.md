---
id: 1836
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:04.381266+00:00
status: superseded
corroborations: 1
supersedes: 1740
superseded_by: 1934
---

# Capture history inside state setters, not in loop call sites

When adding a history ring for a state field, append inside the setter (`set_prompt_efficiency_baseline`), not in `skill_prompt_eval_loop.py`. The regression pin and any future caller drive the setter directly, so history capture is automatic.

**Why:** Call-site appends get skipped when the setter is invoked from a new path; setter-side capture is path-invariant and keeps trailing-window semantics unchanged.
